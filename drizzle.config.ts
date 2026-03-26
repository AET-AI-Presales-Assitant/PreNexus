import { defineConfig } from 'drizzle-kit';

export default defineConfig({
  schema: './db/schema/schema.ts',
  out: './drizzle',
  dialect: 'postgresql',
  dbCredentials: {
    url: 'postgresql://enterprise_user:enterprise_password@127.0.0.1:5434/enterprise_rag',
  },
});
