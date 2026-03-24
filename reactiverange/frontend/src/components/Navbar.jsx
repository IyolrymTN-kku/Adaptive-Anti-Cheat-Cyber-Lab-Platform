import { Moon, Shield, Sun } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';

import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';

const navItems = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/studio', label: 'Scenario Studio' },
  { to: '/challenge', label: 'Challenge' },
  { to: '/scoreboard', label: 'Scoreboard' }
];

export default function Navbar() {
  const { theme, toggleTheme } = useTheme();
  const { user, logout } = useAuth();
  const location = useLocation();

  return (
    <nav className="sticky top-0 z-40 border-b border-green-700/20 bg-white/90 px-4 py-3 text-green-700 backdrop-blur dark:border-green-500/20 dark:bg-gray-900/90 dark:text-green-400">
      <div className="mx-auto flex w-full max-w-7xl items-center justify-between">
        <div className="flex items-center gap-2 font-display text-lg font-semibold">
          <Shield className="h-5 w-5" />
          <span>ReactiveRange</span>
        </div>

        <div className="hidden gap-2 md:flex">
          {navItems.map((item) => {
            const active = location.pathname === item.to;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`rounded-md px-3 py-2 text-sm transition ${
                  active
                    ? 'bg-green-600 text-white dark:bg-green-500/25 dark:text-green-300'
                    : 'hover:bg-green-500/10'
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={toggleTheme}
            className="rounded-full border border-green-500/40 p-2 transition hover:bg-green-500/10"
            aria-label="Toggle theme"
          >
            {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>

          {user ? (
            <>
              <span className="hidden text-xs md:block">
                {user.username} ({user.role})
              </span>
              <button
                type="button"
                onClick={logout}
                className="rounded-md bg-red-600 px-3 py-2 text-xs font-semibold text-white hover:bg-red-700"
              >
                Logout
              </button>
            </>
          ) : null}
        </div>
      </div>
    </nav>
  );
}
