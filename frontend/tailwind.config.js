/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#121316",
        surface: "#121316",
        "surface-container-low": "#1b1b1f",
        "surface-container": "#1f1f23",
        "surface-container-high": "#292a2d",
        "surface-container-highest": "#343538",
        primary: "#a8e8ff",
        "primary-container": "#00d4ff",
        secondary: "#ffb95a",
        tertiary: "#dfdaff",
        "on-surface": "#e3e2e6",
        "on-surface-variant": "#bbc9cf",
        "outline-variant": "#3c494e",
        error: "#ffb4ab",
      },
      fontFamily: {
        headline: ["Space Grotesk", "sans-serif"],
        body: ["Inter", "sans-serif"],
        data: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
}
