import { FormEvent } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Shield,
  Users,
  User as UserIcon,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  ArrowRight,
  Lock,
  Mail,
} from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Role } from '../lib/vectorStore';

interface AuthScreenProps {
  authMode: 'select' | 'login' | 'register';
  userRole: Role;
  onAuthModeChange: (mode: 'select' | 'login' | 'register') => void;
  onUserRoleChange: (role: Role) => void;
  onContinueAsGuest: () => void;
  handleAuth: (e: FormEvent) => void;
  authForm: any;
  onAuthFormChange: (form: any) => void;
  authError: string | null;
  authSuccess: string | null;
  isAuthenticating: boolean;
}

export function AuthScreen({
  authMode,
  userRole,
  onAuthModeChange,
  onUserRoleChange,
  onContinueAsGuest,
  handleAuth,
  authForm,
  onAuthFormChange,
  authError,
  authSuccess,
  isAuthenticating,
}: AuthScreenProps) {
  return (
    <div className='h-screen w-full bg-white flex font-sans overflow-hidden'>
      {/* Background Decorative Elements */}
      <div className='absolute top-0 left-0 w-full h-full overflow-hidden z-0 pointer-events-none'>
        <div className='absolute top-[-10%] right-[-5%] w-[500px] h-[500px] bg-indigo-100/50 rounded-full blur-[100px]' />
        <div className='absolute bottom-[-10%] left-[-5%] w-[600px] h-[600px] bg-violet-100/40 rounded-full blur-[120px]' />
      </div>

      <div className='w-full h-full flex flex-row md:flex-row items-stretch'>
        {/* Left Panel - Branding */}
        <div className='hidden md:block w-1/2 relative bg-[#0A1E40]'>
          <img
            src='/images/left-panel.png'
            alt='AI Presales Assistant'
            className='absolute inset-0 w-full h-full object-cover'
          />
        </div>

        {/* Right Panel - Auth Form */}
        <div className='w-full md:w-1/2 flex items-center justify-center p-8 bg-white relative'>
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.4 }}
            className='w-full max-w-md bg-white/80 backdrop-blur-xl md:bg-white'
          >
            <div className='md:hidden flex items-center gap-3 mb-8'></div>

            <AnimatePresence mode='wait'>
              {authMode === 'select' ? (
                <motion.div
                  key='select'
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  className='space-y-6'
                >
                  <div className='text-center md:text-left mb-8'>
                    <h2 className='text-2xl font-bold text-neutral-900'>
                      Welcome Back
                    </h2>
                    <p className='text-neutral-500 mt-2'>
                      Choose your access method to continue
                    </p>
                  </div>

                  <div className='space-y-4'>
                    <button
                      onClick={() => {
                        onAuthModeChange('login');
                        onUserRoleChange('Employee');
                      }}
                      className='w-full p-4 rounded-2xl bg-white border-2 border-neutral-100 hover:border-indigo-600 hover:bg-indigo-50/50 transition-all group text-left shadow-sm hover:shadow-md relative overflow-hidden'
                    >
                      <div className='flex items-center gap-4 relative z-10'>
                        <div className='w-12 h-12 bg-indigo-100 text-indigo-600 rounded-xl flex items-center justify-center group-hover:scale-110 transition-transform'>
                          <Users className='w-6 h-6' />
                        </div>
                        <div>
                          <div className='font-bold text-neutral-900 group-hover:text-indigo-700 transition-colors'>
                            Login with Account
                          </div>
                          <div className='text-xs text-neutral-500 mt-1'>
                            Employee access to internal knowledge
                          </div>
                        </div>
                        <ArrowRight className='w-5 h-5 text-neutral-300 group-hover:text-indigo-600 ml-auto transition-colors' />
                      </div>
                    </button>

                    <button
                      onClick={onContinueAsGuest}
                      className='w-full p-4 rounded-2xl bg-white border-2 border-neutral-100 hover:border-green-600 hover:bg-green-50/50 transition-all group text-left shadow-sm hover:shadow-md relative overflow-hidden'
                    >
                      <div className='flex items-center gap-4 relative z-10'>
                        <div className='w-12 h-12 bg-green-100 text-green-600 rounded-xl flex items-center justify-center group-hover:scale-110 transition-transform'>
                          <UserIcon className='w-6 h-6' />
                        </div>
                        <div>
                          <div className='font-bold text-neutral-900 group-hover:text-green-700 transition-colors'>
                            Continue as Guest
                          </div>
                          <div className='text-xs text-neutral-500 mt-1'>
                            Public information access only
                          </div>
                        </div>
                        <ArrowRight className='w-5 h-5 text-neutral-300 group-hover:text-green-600 ml-auto transition-colors' />
                      </div>
                    </button>
                  </div>
                  <div className='pt-8 text-center'>
                    <button
                      onClick={() => {
                        onAuthModeChange('login');
                        onUserRoleChange('Admin');
                      }}
                      className='text-xs font-medium text-neutral-400 hover:text-indigo-600 transition-colors py-2 px-4 rounded-full hover:bg-indigo-50'
                    >
                      System Administrator Access
                    </button>
                  </div>
                </motion.div>
              ) : (
                <motion.div
                  key='form'
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                >
                  <div className='mb-8'>
                    <button
                      type='button'
                      onClick={() => onAuthModeChange('select')}
                      className='text-sm text-neutral-500 hover:text-neutral-900 flex items-center gap-1 mb-4 transition-colors pl-1'
                    >
                      <ArrowRight className='w-4 h-4 rotate-180' /> Back to
                      selection
                    </button>
                    <h2 className='text-2xl font-bold text-neutral-900'>
                      {userRole === 'Admin'
                        ? 'Admin Portal'
                        : authMode === 'login'
                          ? 'Sign In'
                          : 'Create Account'}
                    </h2>
                    <p className='text-neutral-500 mt-2'>
                      {userRole === 'Admin'
                        ? 'Secure access for system administrators'
                        : authMode === 'login'
                          ? 'Enter your credentials to access your account'
                          : 'Fill in your details to get started'}
                    </p>
                  </div>

                  <form onSubmit={handleAuth} className='space-y-5'>
                    {authError && (
                      <motion.div
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className='p-4 bg-red-50 border border-red-100 text-red-600 text-sm rounded-xl flex items-start gap-3'
                      >
                        <AlertTriangle className='w-5 h-5 shrink-0 mt-0.5' />
                        <span>{authError}</span>
                      </motion.div>
                    )}

                    {authSuccess && (
                      <motion.div
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className='p-4 bg-green-50 border border-green-100 text-green-600 text-sm rounded-xl flex items-start gap-3'
                      >
                        <CheckCircle2 className='w-5 h-5 shrink-0 mt-0.5' />
                        <span>{authSuccess}</span>
                      </motion.div>
                    )}

                    {authMode === 'register' && (
                      <div className='space-y-1.5'>
                        <label className='text-xs font-bold text-neutral-500 uppercase tracking-wider ml-1'>
                          Full Name
                        </label>
                        <div className='relative'>
                          <Input
                            type='text'
                            required
                            value={authForm.name}
                            onChange={(e) =>
                              onAuthFormChange({
                                ...authForm,
                                name: e.target.value,
                              })
                            }
                            className='pl-10'
                            placeholder='John Doe'
                          />
                          <UserIcon className='w-5 h-5 text-neutral-400 absolute left-3 top-3' />
                        </div>
                      </div>
                    )}

                    <div className='space-y-1.5'>
                      <label className='text-xs font-bold text-neutral-500 uppercase tracking-wider ml-1'>
                        Username
                      </label>
                      <div className='relative'>
                        <Input
                          type='text'
                          required
                          value={authForm.username}
                          onChange={(e) =>
                            onAuthFormChange({
                              ...authForm,
                              username: e.target.value,
                            })
                          }
                          className='pl-10'
                          placeholder='username'
                        />
                        <Mail className='w-5 h-5 text-neutral-400 absolute left-3 top-3' />
                      </div>
                    </div>

                    <div className='space-y-1.5'>
                      <label className='text-xs font-bold text-neutral-500 uppercase tracking-wider ml-1'>
                        Password
                      </label>
                      <div className='relative'>
                        <Input
                          type='password'
                          required
                          value={authForm.password}
                          onChange={(e) =>
                            onAuthFormChange({
                              ...authForm,
                              password: e.target.value,
                            })
                          }
                          className='pl-10'
                          placeholder='••••••••'
                        />
                        <Lock className='w-5 h-5 text-neutral-400 absolute left-3 top-3' />
                      </div>
                    </div>

                    <div className='pt-2'>
                      <Button
                        type='submit'
                        disabled={isAuthenticating}
                        variant='gradient'
                        size='lg'
                        className='w-full font-bold text-base'
                      >
                        {isAuthenticating ? (
                          <>
                            <Loader2 className='w-5 h-5 animate-spin mr-2' />
                            Processing...
                          </>
                        ) : (
                          <>
                            {authMode === 'login'
                              ? 'Sign In'
                              : 'Create Account'}
                            <ArrowRight className='w-5 h-5 ml-2 group-hover:translate-x-1 transition-transform' />
                          </>
                        )}
                      </Button>
                    </div>

                    {userRole === 'Employee' && (
                      <div className='text-center pt-4'>
                        <p className='text-sm text-neutral-500'>
                          {authMode === 'login'
                            ? "Don't have an account?"
                            : 'Already have an account?'}
                          <button
                            type='button'
                            onClick={() =>
                              onAuthModeChange(
                                authMode === 'login' ? 'register' : 'login',
                              )
                            }
                            className='ml-1 text-indigo-600 font-bold hover:text-indigo-700 hover:underline transition-colors'
                          >
                            {authMode === 'login'
                              ? 'Register now'
                              : 'Login here'}
                          </button>
                        </p>
                      </div>
                    )}
                  </form>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </div>
      </div>
    </div>
  );
}
