/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      // A real, self-contained animation - no new npm dependency needed
      // (the tailwindcss-animate plugin's animate-in/fade-in utilities
      // aren't installed in this project; these keyframes stand in for
      // exactly the one entrance animation actually used, by Toast.tsx).
      keyframes: {
        "toast-in": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        // ---- sign-in / sign-up screens (all used behind `motion-safe:` so people who ask
        // their system for reduced motion get a still page) ----
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(16px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "float-slow": {
          "0%, 100%": { transform: "translate3d(0, 0, 0) scale(1)" },
          "50%": { transform: "translate3d(22px, -30px, 0) scale(1.07)" },
        },
        "float-slower": {
          "0%, 100%": { transform: "translate3d(0, 0, 0) scale(1)" },
          "50%": { transform: "translate3d(-26px, 24px, 0) scale(0.95)" },
        },
        shake: {
          "0%, 100%": { transform: "translateX(0)" },
          "20%": { transform: "translateX(-7px)" },
          "40%": { transform: "translateX(7px)" },
          "60%": { transform: "translateX(-4px)" },
          "80%": { transform: "translateX(4px)" },
        },
        "slide-in-right": {
          "0%": { opacity: "0", transform: "translateX(28px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        "slide-in-left": {
          "0%": { opacity: "0", transform: "translateX(-28px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        "draw-check": {
          "0%": { strokeDashoffset: "26" },
          "100%": { strokeDashoffset: "0" },
        },
        "grow-bar": {
          "0%": { width: "0%" },
          "100%": { width: "100%" },
        },
        "ring-out": {
          "0%": { opacity: "0.55", transform: "scale(0.8)" },
          "100%": { opacity: "0", transform: "scale(1.9)" },
        },
      },
      animation: {
        "toast-in": "toast-in 0.2s ease-out",
        "fade-up": "fade-up 0.7s cubic-bezier(0.16, 1, 0.3, 1) both",
        "float-slow": "float-slow 16s ease-in-out infinite",
        "float-slower": "float-slower 22s ease-in-out infinite",
        shake: "shake 0.45s ease-in-out",
        "slide-in-right": "slide-in-right 0.45s cubic-bezier(0.16, 1, 0.3, 1) both",
        "slide-in-left": "slide-in-left 0.45s cubic-bezier(0.16, 1, 0.3, 1) both",
        "draw-check": "draw-check 0.6s 0.15s ease-out both",
        "grow-bar": "grow-bar 1.2s linear both",
        "ring-out": "ring-out 1.4s ease-out 1",
      },
    },
  },
  plugins: [],
};
