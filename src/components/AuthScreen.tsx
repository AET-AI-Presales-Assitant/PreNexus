import { FormEvent, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Eye,
  EyeOff,
} from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';

interface AuthScreenProps {
  authMode: 'login' | 'register';
  onAuthModeChange: (mode: 'login' | 'register') => void;
  handleAuth: (e: FormEvent) => void;
  authForm: any;
  onAuthFormChange: (form: any) => void;
  authError: string | null;
  authSuccess: string | null;
  isAuthenticating: boolean;
}

export function AuthScreen({
  authMode,
  onAuthModeChange,
  handleAuth,
  authForm,
  onAuthFormChange,
  authError,
  authSuccess,
  isAuthenticating,
}: AuthScreenProps) {
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);

  return (
    <div className='min-h-screen w-full bg-white font-sans relative overflow-hidden'>
      <div className='hidden md:block absolute inset-y-0 left-0 w-1/2 bg-white'>
        <div className='absolute -bottom-28 -left-28 w-[560px] h-[560px] rounded-full bg-[#132e57]/16 blur-[120px]' />
      </div>
      <div className='hidden md:block absolute inset-y-0 right-0 w-1/2 bg-white'>
        <div className='absolute -top-24 -right-24 w-[560px] h-[560px] rounded-full bg-[#132e57]/16 blur-[120px]' />
      </div>

      <div className='w-full max-w-6xl mx-auto flex items-stretch gap-10 px-4 py-10 relative z-10'>
        <div className='hidden md:block w-1/2'>
          <div className='relative h-[560px] rounded-[2rem] overflow-hidden shadow-2xl border border-white/40 bg-black'>
            <img
              src='/images/left-side.png'
              alt='AI Presales Assistant'
              className='absolute inset-0 w-full h-full object-cover'
            />
          </div>
        </div>

        <div className='w-full md:w-1/2 flex items-center'>
          <div className='w-full px-0 md:px-8 sm:px-12 lg:px-14'>
              <AnimatePresence mode='wait'>
                <motion.div
                  key={authMode}
                  initial={{ opacity: 0, x: 12 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -12 }}
                >
                  {authMode === 'login' ? (
                    <>
                      <h1 className='mt-6 text-4xl sm:text-5xl font-extrabold tracking-tight text-[#0b2a55]'>
                        Welcome Back!
                      </h1>
                      <p className='mt-4 text-slate-500 leading-relaxed max-w-md'>
                        Log in to unlock internal knowledge and level up.
                      </p>
                    </>
                  ) : (
                    <h1 className='mt-6 text-4xl sm:text-5xl font-extrabold tracking-tight text-[#0b2a55]'>
                      Join Us Today!
                    </h1>
                  )}

                    <form onSubmit={handleAuth} className='mt-10 space-y-6 max-w-md'>
                      {authError && (
                        <motion.div
                          initial={{ opacity: 0, y: -10 }}
                          animate={{ opacity: 1, y: 0 }}
                          className='p-4 bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl flex items-start gap-3'
                        >
                          <AlertTriangle className='w-5 h-5 shrink-0 mt-0.5' />
                          <span>{authError}</span>
                        </motion.div>
                      )}

                      {authSuccess && (
                        <motion.div
                          initial={{ opacity: 0, y: -10 }}
                          animate={{ opacity: 1, y: 0 }}
                          className='p-4 bg-green-50 border border-green-200 text-green-700 text-sm rounded-xl flex items-start gap-3'
                        >
                          <CheckCircle2 className='w-5 h-5 shrink-0 mt-0.5' />
                          <span>{authSuccess}</span>
                        </motion.div>
                      )}

                      {authMode === 'register' && (
                        <div>
                          <label className='text-sm font-semibold text-slate-900'>
                            Full Name
                          </label>
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
                            className='mt-2 h-12 rounded-xl border-slate-300 bg-white'
                            placeholder='Enter your name'
                          />
                        </div>
                      )}

                      <div>
                        <label className='text-sm font-semibold text-slate-900'>
                          Email Address
                        </label>
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
                          className='mt-2 h-12 rounded-xl border-slate-300 bg-white'
                          placeholder='Enter your email'
                        />
                      </div>

                      <div>
                        <label className='text-sm font-semibold text-slate-900'>
                          Password
                        </label>
                        <div className='relative mt-2'>
                          <Input
                            type={showPassword ? 'text' : 'password'}
                            required
                            value={authForm.password}
                            onChange={(e) =>
                              onAuthFormChange({
                                ...authForm,
                                password: e.target.value,
                              })
                            }
                            className='h-12 rounded-xl border-slate-300 bg-white pr-12'
                            placeholder='Enter your password'
                          />
                          <button
                            type='button'
                            className='absolute right-3 top-3 text-slate-500 hover:text-slate-700 transition-colors'
                            onClick={() => setShowPassword((v) => !v)}
                            aria-label={showPassword ? 'Hide password' : 'Show password'}
                          >
                            {showPassword ? (
                              <EyeOff className='w-5 h-5' />
                            ) : (
                              <Eye className='w-5 h-5' />
                            )}
                          </button>
                        </div>
                      </div>

                      {authMode === 'login' ? (
                        <div className='flex items-center justify-between pt-1'>
                          <label className='flex items-center gap-3 text-sm text-slate-500 select-none'>
                            <input
                              type='checkbox'
                              checked={rememberMe}
                              onChange={(e) => setRememberMe(e.target.checked)}
                              className='h-5 w-5 rounded border-slate-300'
                            />
                            Remember me
                          </label>
                          <button
                            type='button'
                            className='text-sm text-slate-500 hover:text-slate-700 transition-colors'
                          >
                            Forgot Password?
                          </button>
                        </div>
                      ) : null}

                      <div className='pt-2'>
                        <Button
                          type='submit'
                          disabled={isAuthenticating}
                          className='w-full h-12 rounded-xl bg-[#0b2a55] hover:bg-[#082247] text-white font-semibold'
                        >
                          {isAuthenticating ? (
                            <>
                              <Loader2 className='w-5 h-5 animate-spin mr-2' />
                              Processing...
                            </>
                          ) : authMode === 'login' ? (
                            'Login to Your Space'
                          ) : (
                            'Create Account'
                          )}
                        </Button>
                      </div>
                        <div className='text-center pt-4 text-sm text-slate-500'>
                          {authMode === 'login' ? (
                            <>
                              <span>Don&apos;t have an account?</span>
                              <button
                                type='button'
                                onClick={() => onAuthModeChange('register')}
                                className='ml-2 text-slate-700 font-semibold hover:underline'
                              >
                                Register now
                              </button>
                            </>
                          ) : (
                            <>
                              <span>Already have an account?</span>
                              <button
                                type='button'
                                onClick={() => onAuthModeChange('login')}
                                className='ml-2 text-slate-700 font-semibold hover:underline'
                              >
                                Login here
                              </button>
                            </>
                          )}
                        </div>
                    </form>
                  </motion.div>
              </AnimatePresence>
          </div>
        </div>
      </div>
    </div>
  );
}
