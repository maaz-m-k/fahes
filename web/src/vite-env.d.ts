/// <reference types="vite/client" />
interface ImportMetaEnv { readonly VITE_ENGINE?: string; readonly VITE_ENGINE_URL?: string }
declare module '*.txt?raw' { const s: string; export default s; }
