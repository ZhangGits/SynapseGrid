/**
 * 类型声明文件 — 为 Vite 构建的 CSS 导入和第三方库提供类型支持
 */
declare module "*.css" {
  const content: string;
  export default content;
}

// cytoscape-dagre 没有 @types 包，声明为 any 模块
declare module "cytoscape-dagre";