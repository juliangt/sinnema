/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // Paleta oscura de la UI 3D (variables en src/index.css).
      colors: {
        fondo: 'hsl(var(--fondo) / <alpha-value>)',
        panel: 'hsl(var(--panel) / <alpha-value>)',
        'panel-alto': 'hsl(var(--panel-alto) / <alpha-value>)',
        borde: 'hsl(var(--borde) / <alpha-value>)',
        texto: 'hsl(var(--texto) / <alpha-value>)',
        'texto-suave': 'hsl(var(--texto-suave) / <alpha-value>)',
        acento: 'hsl(var(--acento) / <alpha-value>)',
      },
    },
  },
  plugins: [],
}
