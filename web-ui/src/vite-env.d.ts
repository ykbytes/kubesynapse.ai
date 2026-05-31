/// <reference types="vite/client" />

declare module "*.mmd?raw" {
  const content: string;
  export default content;
}
