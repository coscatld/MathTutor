"use client";
import {useI18n} from "@/lib/i18n";

/** Explicit UI copy for server-owned loading boundaries; never document text. */
export default function LocalizedText({message}: {message: string}) {
  const {t} = useI18n();
  return <>{t(message)}</>;
}
