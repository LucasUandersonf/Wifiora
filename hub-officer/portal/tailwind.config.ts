import type { Config } from "tailwindcss";

// Paleta: tinta azul-ardósia + verde-petróleo de "verificado". Fontes do sistema (zero download).
export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#15202b", soft: "#4a5565" },
        verified: { DEFAULT: "#0d7a5f", soft: "#e2f4ee", dark: "#4fd1a5", darksoft: "#0f2a22" },
        accent: { DEFAULT: "#1d5fd1", dark: "#7fb0ff" },
      },
      maxWidth: { prose: "68ch" },
    },
  },
  plugins: [],
} satisfies Config;
