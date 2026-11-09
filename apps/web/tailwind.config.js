/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        background: '#0a0d14',
        surface: {
          50: '#1e2433',
          100: '#181d2a',
          200: '#141824',
          300: '#10141e',
          400: '#0d1019',
          500: '#0a0d14',
        },
        border: '#232b3e',
        primary: {
          DEFAULT: '#0284c7', // cyan-600
          hover: '#0369a1',
          foreground: '#ffffff',
          light: '#38bdf8',
        },
        accent: {
          cyan: '#06b6d4',
          blue: '#3b82f6',
          emerald: '#10b981',
          amber: '#f59e0b',
          rose: '#f43f5e',
        },
        muted: {
          DEFAULT: '#64748b',
          foreground: '#94a3b8',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
};

