import type {PluginCommand} from "../community/api";

export function slashQuery(text: string): string | null {
  const match = /^\/([a-z0-9_-]*)$/i.exec(text);
  return match && match[1].length <= 32 ? match[1].toLowerCase() : null;
}
export function isSlashCommand(text: string) {return /^\/[a-z][a-z0-9_-]{1,31}(?:\s|$)/.test(text);}
export function availableCommands(items: PluginCommand[], query: string) {
  return items.filter(item => item.enabled === true && item.runtime_available === true && /^[a-z][a-z0-9_-]{1,31}$/.test(item.command) && item.command.startsWith(query)).slice(0, 12);
}
