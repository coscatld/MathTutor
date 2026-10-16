export type CommunityView = "documents" | "plugins";
export function communityView(tab: string | null): CommunityView { return tab === "plugins" ? "plugins" : "documents"; }

type DocumentFile = {name: string; size: number; lastModified: number; webkitRelativePath?: string};
export function documentPath(file: DocumentFile) { return file.webkitRelativePath || file.name; }
export function prepareDocuments<T extends DocumentFile>(selected: T[], folder = false): {files: T[]; skipped: number} {
  const files = folder ? selected.filter(file => {
    const parts = documentPath(file).split(/[\\/]/);
    return !parts.some(part => part.startsWith(".")) && /\.(md|markdown|txt)$/i.test(file.name);
  }) : selected;
  const skipped = selected.length - files.length;
  if (!files.length) throw new Error(folder ? "这个文件夹没有可导入的文本资料。" : "请先选择要导入的文件。");
  if (files.length > 1000) throw new Error("一次最多导入 1000 份文本资料，请分批选择。");
  if (files.reduce((sum, file) => sum + file.size, 0) > 20 * 1024 * 1024) throw new Error("资料总大小不能超过 20 MB，请分批导入。");
  const bundles = files.filter(file => /\.(zip|mathtutor|json)$/i.test(file.name));
  if (bundles.length && files.length !== 1) throw new Error("题库文件请单独导入，其他文本资料可以一起选择。");
  if (files.some(file => !/\.(md|markdown|txt|zip|mathtutor|json)$/i.test(file.name))) throw new Error("请选择学习笔记、文本资料或已有题库文件。");
  if (files.some(file => /\.(md|markdown|txt)$/i.test(file.name) && file.size > 1024 * 1024)) throw new Error("每份文本资料不能超过 1 MB，请拆分后再导入。");
  return {files, skipped};
}
