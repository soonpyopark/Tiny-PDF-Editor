/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{js,jsx,html}', './shared/**/*.js'],
  theme: {
    extend: {
      colors: {
        // Accent tokens resolve at runtime from CSS variables (styles/index.css),
        // which 환경설정 → 일반 → 테마 색상 rewrites. See shared/theme.js.
        app: {
          sidebar: 'rgb(var(--app-sidebar) / <alpha-value>)',
          sidebarHover: 'rgb(var(--app-sidebar-hover) / <alpha-value>)',
          accent: 'rgb(var(--app-accent) / <alpha-value>)',
          accentHover: 'rgb(var(--app-accent-hover) / <alpha-value>)',
          accentSoft: 'rgb(var(--app-accent-soft) / <alpha-value>)',
          accentSoftHover: 'rgb(var(--app-accent-soft-hover) / <alpha-value>)',
          accentBorder: 'rgb(var(--app-accent-border) / <alpha-value>)',
          accentText: 'rgb(var(--app-accent-text) / <alpha-value>)',
          surface: '#f8fafc',
          border: '#e2e8f0',
          muted: '#64748b',
        },
      },
      fontFamily: {
        sans: ['"Segoe UI"', '"Malgun Gothic"', 'system-ui', '-apple-system', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
