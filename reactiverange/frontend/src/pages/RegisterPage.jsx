import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import apiClient from '../api/client';

export default function RegisterPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    username: '',
    email: '',
    password: '',
    role: 'student'
  });
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const onChange = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const onSubmit = async (event) => {
    event.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await apiClient.post('/api/auth/register', form);
      navigate('/login');
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto mt-16 w-full max-w-md px-4 animate-fadeIn">
      <div className="terminal-panel rounded-xl p-6">
        <h1 className="font-display text-2xl font-bold text-green-400">Create Operator Account</h1>
        <p className="mt-2 text-sm text-slate-300 dark:text-slate-300 text-slate-600">Join the range as student or instructor.</p>

        <form className="mt-6 space-y-4" onSubmit={onSubmit}>
          <input
            value={form.username}
            onChange={(event) => onChange('username', event.target.value)}
            placeholder="Username"
            required
            className="w-full rounded-md border border-green-500/30 bg-gray-900/40 px-3 py-2 text-sm text-green-300 outline-none focus:border-green-400 dark:bg-gray-900/40 bg-white"
          />
          <input
            type="email"
            value={form.email}
            onChange={(event) => onChange('email', event.target.value)}
            placeholder="Email"
            required
            className="w-full rounded-md border border-green-500/30 bg-gray-900/40 px-3 py-2 text-sm text-green-300 outline-none focus:border-green-400 dark:bg-gray-900/40 bg-white"
          />
          <input
            type="password"
            minLength={8}
            value={form.password}
            onChange={(event) => onChange('password', event.target.value)}
            placeholder="Password (min 8 chars)"
            required
            className="w-full rounded-md border border-green-500/30 bg-gray-900/40 px-3 py-2 text-sm text-green-300 outline-none focus:border-green-400 dark:bg-gray-900/40 bg-white"
          />

          <select
            value={form.role}
            onChange={(event) => onChange('role', event.target.value)}
            className="w-full rounded-md border border-green-500/30 bg-gray-900/40 px-3 py-2 text-sm text-green-300 outline-none focus:border-green-400 dark:bg-gray-900/40 bg-white"
          >
            <option value="student">Student</option>
            <option value="instructor">Instructor</option>
          </select>

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-green-600 px-4 py-2 font-semibold text-white hover:bg-green-500 disabled:opacity-60"
          >
            {submitting ? 'Creating...' : 'Create Account'}
          </button>
        </form>

        {error ? <p className="mt-4 text-sm text-red-400">{error}</p> : null}

        <p className="mt-6 text-sm text-slate-300 dark:text-slate-300 text-slate-600">
          Already registered?{' '}
          <Link className="text-green-400 underline" to="/login">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
