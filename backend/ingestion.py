import os
import uuid
from typing import List, Literal
from pydantic import BaseModel, Field

# LangChain Imports
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, UnstructuredExcelLoader, TextLoader
from langchain_experimental.text_splitter import SemanticChunker
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_chroma import Chroma
from langchain_classic.retrievers import MultiVectorRetriever
from langchain_core.stores import InMemoryByteStore
from langchain_core.documents import Document

import fitz  # PyMuPDF
import pdfplumber
import base64

def process_pdf_complex(file_path: str, llm) -> List[Document]:
    """
    Complex PDF processing:
    1. Use pdfplumber to extract regular text.
    2. Use PyMuPDF (fitz) to convert pages into images.
    3. Use Gemini Vision to describe image structure (such as tables, charts, layout).
    4. Combine the results into a single document.
    """
    docs = []
    doc_fitz = fitz.open(file_path)

    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            # 1. Extract text by pdfplumber
            extracted_text = page.extract_text() or ""
            
            # 2. Render image of the page using PyMuPDF
            fitz_page = doc_fitz.load_page(page_num)
            pix = fitz_page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_bytes = pix.tobytes("png")
            img_base64 = base64.b64encode(img_bytes).decode('utf-8')
            
            # 3. Using Vision LLM to analyze page structure
            vision_prompt = """
                You are an expert in analyzing document layouts and structures.
                Please read the entire content of this slide/page and extract ALL information.

                Return a JSON with the following structure:
                {
                "slide_title": "slide title if any",
                "content_type": "diagram|table|text|mixed",
                "main_concepts": ["concepts 1", "concepts 2"],
                "relationships": [
                    {"from": "A", "to": "B", "relationship": "relationship description"}
                ],
                "key_terms": ["key terms"],
                "full_description": "full description of the entire content, including diagram/flowchart",
                "category": "skills_tech|case_study|presales|other"
                }

                IMPORTANT:
                - Read ALL text in the diagram, including small text in boxes
                - Describe the tree/flowchart structure fully (parent → children)
                - Do not miss any information in the image
            """
            
            # Initialize vision model
            try:
                vision_llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite-preview", temperature=0)
                vision_msg = vision_llm.invoke(
                    [
                        {"role": "user", "content": [
                            {"type": "text", "text": vision_prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}}
                        ]}
                    ]
                )
                vision_text = vision_msg.content
            except Exception as e:
                print(f"Error occurred while calling Vision API on page {page_num + 1}: {e}")
                vision_text = ""

            # 4. Combine content
            combined_content = f"--- PAGE {page_num + 1} ---\n\n"
            combined_content += f"[Extracted Text]:\n{extracted_text}\n\n"
            combined_content += f"[Vision Analysis]:\n{vision_text}\n"
            
            docs.append(Document(
                page_content=combined_content,
                metadata={"source": file_path, "page": page_num + 1}
            ))
            
    doc_fitz.close()
    return docs

# 1. Document Loader Factory
def load_file(file_path: str, llm=None) -> List[Document]:
    ext = os.path.splitext(file_path)[-1].lower()
    if ext == '.pdf':
        if llm is None:
            raise ValueError("Provide an LLM instance for complex PDF processing.")
        return process_pdf_complex(file_path, llm)
    elif ext == '.docx':
        loader = Docx2txtLoader(file_path)
    elif ext in ['.xlsx', '.xls']:
        loader = UnstructuredExcelLoader(file_path)
    elif ext == '.txt':
        loader = TextLoader(file_path, encoding='utf-8')
    else:
        raise ValueError(f"File format not supported: {ext}")
    return loader.load()

# 2. Schema định nghĩa metadata cho LLM trích xuất
class ChunkClassification(BaseModel):
    category: Literal["skills_tech", "case_study", "presales", "other"] = Field(
        description="""
            You are an expert in classifying presales documents.
            Classify the following text into one of the three categories based on its main content:

            - skills_tech: skills, technology, solutions, approach tech stack mentioned in the text
            - case_study: specific projects, clients, issues, results achieved
            - presales: sales process, checklists, workflow for client engagement

            If the text does not belong to any of the above categories → return "other"
            Only return the correct category name, no explanations.
        """
    )
    tags: List[str] = Field(description="Important keywords (technology names, client names, business domains) mentioned in the text")
    summary: str = Field(description="Brief summary of the content of this text chunk (used for search)")

class KnowledgePipeline:
    def __init__(self, api_key: str):
        os.environ["GOOGLE_API_KEY"] = api_key
        self.llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite-preview", temperature=0)
        self.embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
        
        self.vectorstore = Chroma(
            collection_name="presales_summaries",
            embedding_function=self.embeddings,
            persist_directory="./chroma_data"
        )
        
        self.store = InMemoryByteStore()
        self.id_key = "doc_id"
        
        self.retriever = MultiVectorRetriever(
            vectorstore=self.vectorstore,
            byte_store=self.store,
            id_key=self.id_key,
        )
        
        # Initialize Semantic Chunker (cut chunk by semantic meaning, not by length)
        self.text_splitter = SemanticChunker(self.embeddings, breakpoint_threshold_type="percentile")

    def process_and_ingest(self, file_path: str, role: str = "Employee"):
        print(f"1. Reading file: {file_path}...")
        docs = load_file(file_path, self.llm)
        
        # Combine all page contents into one full text for better semantic chunking.
        full_text = "\n\n".join([d.page_content for d in docs])
        
        print("2. Performing Semantic Chunking...")
        chunks = self.text_splitter.create_documents([full_text])
        print(f"   -> Successfully split into {len(chunks)} semantic chunks.")
        
        print("3. Extracting Metadata & Generating Summary with LLM...")
        structured_llm = self.llm.with_structured_output(ChunkClassification)
        
        doc_ids = [str(uuid.uuid4()) for _ in chunks]
        summary_docs = []
        
        for i, chunk in enumerate(chunks):
            try:
                analysis: ChunkClassification = structured_llm.invoke(
                    f"Analyze the following text:\n\n{chunk.page_content}"
                )
                
                # Check if analysis is None or missing attributes
                if not analysis:
                    print(f"   ! LLM returned empty analysis for chunk {i+1}")
                    continue

                chunk.metadata = {
                    "source": file_path,
                    "category": analysis.category,
                    "tags": ", ".join(analysis.tags) if hasattr(analysis, 'tags') else "",
                    "role": role,
                    self.id_key: doc_ids[i]
                }
                
                summary_doc = Document(
                    page_content=analysis.summary if hasattr(analysis, 'summary') else chunk.page_content[:200],
                    metadata={
                        self.id_key: doc_ids[i],
                        "category": analysis.category,
                        "source": file_path,
                        "role": role
                    }
                )
                summary_docs.append(summary_doc)
                
            except Exception as e:
                print(f"   ! Error occurred while processing chunk {i+1}: {e}")
                
        print("4. Saving to Multi-Vector Store (Chroma)...")
        # Lưu Full Text vào ByteStore
        self.store.mset(list(zip(doc_ids, chunks)))
        
        # Lưu Summary vào Vector DB (Chroma)
        if summary_docs:
            self.vectorstore.add_documents(summary_docs)
            
        print("Complete Ingestion!\n")
        
    def query(self, question: str) -> List[Document]:
        """Search for relevant documents based on the question."""
        print(f"Searching for: '{question}'...")
        results = self.retriever.invoke(question)
        return results

if __name__ == "__main__":
    GEMINI_API_KEY = "AIzaSyBM_Xgk-b6M31axc_RqmY6nxEmKokX8DsU"
    
    pipeline = KnowledgePipeline(api_key=GEMINI_API_KEY)
