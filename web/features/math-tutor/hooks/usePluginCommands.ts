"use client";
import {useCallback, useEffect, useRef, useState} from "react";
import {communityApi, PLUGINS_CHANGED, type PluginCommand} from "../community/api";

export function usePluginCommands(active: boolean) {
  const [items, setItems] = useState<PluginCommand[]>([]), [loading, setLoading] = useState(false), [error, setError] = useState("");
  const generation = useRef(0);
  const refresh = useCallback(async () => {
    const current = ++generation.current; setLoading(true); setItems([]); setError("");
    try {const value = await communityApi<{items: PluginCommand[]}>("/plugins/commands"); if (current === generation.current) setItems(Array.isArray(value.items) ? value.items : []);}
    catch {if (current === generation.current) {setItems([]); setError("插件命令暂时无法读取，请重试。");}}
    finally {if (current === generation.current) setLoading(false);}
  }, []);
  useEffect(() => {
    if (!active) {generation.current++; setItems([]); setLoading(false); setError(""); return;}
    void refresh();
    const changed = () => {void refresh();};
    window.addEventListener(PLUGINS_CHANGED, changed);
    return () => {generation.current++; window.removeEventListener(PLUGINS_CHANGED, changed);};
  }, [active, refresh]);
  return {items, loading, error, refresh};
}
