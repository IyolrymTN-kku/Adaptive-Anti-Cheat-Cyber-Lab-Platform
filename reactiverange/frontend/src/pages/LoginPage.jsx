import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import apiClient from '../api/client';
import { useAuth } from '../context/AuthContext';

function OtpBoxes({ value, setValue, disabled }) {
  const refs = useRef([]);

  const digits = useMemo(() => {
    const arr = new Array(6).fill('');
    value.split('').slice(0, 6).forEach((char, i) => {
      arr[i] = char;
    });
    return arr;
  }, [value]);

  const onChange = (idx, next) => {
    if (!/^\d?$/.test(next)) return;
    const copy = [...digits];
    copy[idx] = next;
    const joined = copy.join('');
    setValue(joined);
    if (next && idx < 5) refs.current[idx + 1]?.focus();
  };

  const onKeyDown = (idx, event) => {
    if (event.key === 'Backspace' && !digits[idx] && idx > 0) {
      refs.current[idx - 1]?.focus();
    }
  };

  return (
    <div className="mt-4 flex gap-2">
      {digits.map((digit, idx) => (
        <input
          key={idx}
          ref={(el) => {
            refs.current[idx] = el;
          }}
          value={digit}
          onChange={(event) => onChange(idx, event.target.value)}
          onKeyDown={(event) => onKeyDown(idx, event)}
          maxLength={1}
          disabled={disabled}
          className="h-12 w-12 rounded-md border border-green-500/30 bg-gray-900/40 text-center font-mono text-xl text-green-400 focus:border-green-400 focus:outline-none dark:bg-gray-900/40 dark:text-green-400 bg-white text-green-700"
        />
      ))}
    </div>
  );
}

export default function LoginPage() {
  const { loginWithOtp } = useAuth();
  const navigate = useNavigate();

  const [step, setStep] = useState('credentials');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [otp, setOtp] = useState('');
  const [otpRemaining, setOtpRemaining] = useState(300);
  const [resendRemaining, setResendRemaining] = useState(60);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (step !== 'otp') return undefined;

    const timer = setInterval(() => {
      setOtpRemaining((prev) => Math.max(prev - 1, 0));
      setResendRemaining((prev) => Math.max(prev - 1, 0));
    }, 1000);

    return () => clearInterval(timer);
  }, [step]);

  const formattedOtpTimer = `${String(Math.floor(otpRemaining / 60)).padStart(1, '0')}:${String(otpRemaining % 60).padStart(2, '0')}`;

  const submitCredentials = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      await apiClient.post('/api/auth/login', { email, password });
      setStep('otp');
      setOtpRemaining(300);
      setResendRemaining(60);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const verifyOtp = async (event) => {
    event.preventDefault();
    if (otp.length !== 6) {
      setError('Enter your 6-digit OTP');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      await loginWithOtp({ email, otp });
      navigate('/dashboard');
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const resendOtp = async () => {
    setSubmitting(true);
    setError('');
    try {
      await apiClient.post('/api/auth/login', { email, password });
      setOtpRemaining(300);
      setResendRemaining(60);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto mt-16 w-full max-w-md px-4 animate-fadeIn">
      <div className="terminal-panel rounded-xl p-6">
        <h1 className="font-display text-2xl font-bold text-green-400">Access ReactiveRange</h1>
        <p className="mt-2 text-sm text-slate-300 dark:text-slate-300 text-slate-600">
          {step === 'credentials' ? 'Sign in to receive your OTP challenge key.' : 'Verify your OTP to unlock the command deck.'}
        </p>

        {step === 'credentials' ? (
          <form className="mt-6 space-y-4" onSubmit={submitCredentials}>
            <input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="Email"
              className="w-full rounded-md border border-green-500/30 bg-gray-900/40 px-3 py-2 text-sm text-green-300 outline-none focus:border-green-400 dark:bg-gray-900/40 bg-white"
            />
            <input
              type="password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Password"
              className="w-full rounded-md border border-green-500/30 bg-gray-900/40 px-3 py-2 text-sm text-green-300 outline-none focus:border-green-400 dark:bg-gray-900/40 bg-white"
            />
            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-md bg-green-600 px-4 py-2 font-semibold text-white transition hover:bg-green-500 disabled:opacity-60"
            >
              {submitting ? 'Signing in...' : 'Continue'}
            </button>
          </form>
        ) : (
          <form className="mt-6" onSubmit={verifyOtp}>
            <div className="rounded-md border border-green-500/20 bg-green-500/5 px-3 py-2 text-xs">
              OTP expires in <span className="font-mono">{formattedOtpTimer}</span>
            </div>
            <OtpBoxes value={otp} setValue={setOtp} disabled={submitting || otpRemaining === 0} />

            <button
              type="submit"
              disabled={submitting || otpRemaining === 0}
              className="mt-4 w-full rounded-md bg-green-600 px-4 py-2 font-semibold text-white transition hover:bg-green-500 disabled:opacity-60"
            >
              {submitting ? 'Verifying...' : 'Verify OTP'}
            </button>

            <button
              type="button"
              onClick={resendOtp}
              disabled={submitting || resendRemaining > 0}
              className="mt-2 w-full rounded-md border border-green-500/30 px-4 py-2 text-sm disabled:opacity-50"
            >
              {resendRemaining > 0 ? `Resend OTP in ${resendRemaining}s` : 'Resend OTP'}
            </button>
          </form>
        )}

        {error ? <p className="mt-4 text-sm text-red-400">{error}</p> : null}

        <p className="mt-6 text-sm text-slate-300 dark:text-slate-300 text-slate-600">
          New operator?{' '}
          <Link className="text-green-400 underline" to="/register">
            Create account
          </Link>
        </p>
      </div>
    </div>
  );
}
