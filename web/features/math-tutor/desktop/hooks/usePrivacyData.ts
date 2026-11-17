'use client'

import type { MessageParams } from '@/lib/i18n'
import { useCallback, useEffect, useState } from 'react'
import {
  deleteDocument,
  deleteEducationalHistory,
  deleteMemory,
  DesktopApiError,
  fetchDocuments,
  fetchMemories,
  fetchStudentExport,
  fetchStudentSummary,
  purgeDocuments,
  purgeMemory,
  rebuildIndexes,
  recomputeLearningProfile,
} from '../lib/desktop-api'
import type { DesktopDocument, DesktopMemory, StudentSummary } from '../types'

export interface PrivacyDataOptions {
  /** Injectable fetchers — tests pass fakes. */
  fetchMemoriesFn?: typeof fetchMemories
  fetchDocumentsFn?: typeof fetchDocuments
  fetchStudentSummaryFn?: typeof fetchStudentSummary
  deleteMemoryFn?: typeof deleteMemory
  deleteDocumentFn?: typeof deleteDocument
  purgeDocumentsFn?: typeof purgeDocuments
  purgeMemoryFn?: typeof purgeMemory
  deleteHistoryFn?: typeof deleteEducationalHistory
  rebuildIndexesFn?: typeof rebuildIndexes
  fetchExportFn?: typeof fetchStudentExport
}

export function usePrivacyData({
  fetchMemoriesFn = fetchMemories,
  fetchDocumentsFn = fetchDocuments,
  fetchStudentSummaryFn = fetchStudentSummary,
  deleteMemoryFn = deleteMemory,
  deleteDocumentFn = deleteDocument,
  purgeDocumentsFn = purgeDocuments,
  purgeMemoryFn = purgeMemory,
  deleteHistoryFn = deleteEducationalHistory,
  rebuildIndexesFn = rebuildIndexes,
  fetchExportFn = fetchStudentExport,
}: PrivacyDataOptions) {
  const [memories, setMemories] = useState<DesktopMemory[]>([])
  const [documents, setDocuments] = useState<DesktopDocument[]>([])
  const [summary, setSummary] = useState<StudentSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [confirmMemoryId, setConfirmMemoryId] = useState<string | null>(null)
  const [confirmDocId, setConfirmDocId] = useState<string | null>(null)
  const [confirmDanger, setConfirmDanger] = useState<string | null>(null)
  const [message, setMessage] = useState<{
    kind: 'ok' | 'error'
    text: string
    params?: MessageParams
  } | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [memoryList, documentList, summaryData] = await Promise.all([
        fetchMemoriesFn(),
        fetchDocumentsFn(),
        fetchStudentSummaryFn(),
      ])
      setMemories(memoryList)
      setDocuments(documentList)
      setSummary(summaryData)
    } catch (err) {
      setMessage({
        kind: 'error',
        text: err instanceof DesktopApiError ? err.message : '读取数据失败，请稍后再试。',
      })
    } finally {
      setLoading(false)
    }
  }, [fetchMemoriesFn, fetchDocumentsFn, fetchStudentSummaryFn])

  useEffect(() => {
    load().catch(() => undefined)
  }, [load])

  const handleDeleteMemory = async (memory: DesktopMemory) => {
    setBusyId(memory.memory_id)
    try {
      await deleteMemoryFn(memory.memory_id)
      setMemories(list => list.filter(m => m.memory_id !== memory.memory_id))
      setConfirmMemoryId(null)
      setMessage({ kind: 'ok', text: '已删除这条记忆。' })
    } catch (err) {
      setMessage({
        kind: 'error',
        text: err instanceof DesktopApiError ? err.message : '删除失败，请稍后再试。',
      })
    } finally {
      setBusyId(null)
    }
  }

  const handleDeleteDocument = async (doc: DesktopDocument) => {
    setBusyId(doc.document_id)
    try {
      await deleteDocumentFn(doc.document_id)
      setDocuments(list => list.filter(d => d.document_id !== doc.document_id))
      setConfirmDocId(null)
      setMessage({ kind: 'ok', text: '已删除「{filename}」', params: { filename: doc.filename } })
    } catch (err) {
      setMessage({
        kind: 'error',
        text: err instanceof DesktopApiError ? err.message : '删除失败，请稍后再试。',
      })
    } finally {
      setBusyId(null)
    }
  }

  const handleDanger = async (key: string, run: () => Promise<void>, okText: string) => {
    setBusyId(key)
    try {
      await run()
      setConfirmDanger(null)
      setMessage({ kind: 'ok', text: okText })
      await load()
    } catch (err) {
      setConfirmDanger(null)
      setMessage({
        kind: 'error',
        text: err instanceof DesktopApiError ? err.message : '操作失败，请稍后再试。',
      })
    } finally {
      setBusyId(null)
    }
  }

  const handleRebuildIndexes = async () => {
    setBusyId('rebuild-indexes')
    try {
      const result = await rebuildIndexesFn()
      const rebuilt = Object.values(result.documents).filter(d => d.status === 'rebuilt').length
      setMessage({
        kind: 'ok',
        text:
          rebuilt > 0
            ? '已重建 {rebuilt} 份资料的检索索引。'
            : '当前未配置向量模型，检索索引暂不可用（词法检索不受影响）。',
        params: { rebuilt },
      })
    } catch (err) {
      setMessage({
        kind: 'error',
        text: err instanceof DesktopApiError ? err.message : '重建索引失败，请稍后再试。',
      })
    } finally {
      setBusyId(null)
    }
  }

  const handleExport = async () => {
    setBusyId('export')
    try {
      const body = await fetchExportFn()
      const blob = new Blob([JSON.stringify(body, null, 2)], {
        type: 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `mathtutor-export-${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
      setMessage({ kind: 'ok', text: '已导出我的数据（JSON 文件）。' })
    } catch (err) {
      setMessage({
        kind: 'error',
        text: err instanceof DesktopApiError ? err.message : '导出失败，请稍后再试。',
      })
    } finally {
      setBusyId(null)
    }
  }

  const handleRecompute = async () => {
    setBusyId('recompute')
    try {
      await recomputeLearningProfile()
      await load()
      setMessage({ kind: 'ok', text: '已根据有效记录重新计算学习画像。' })
    } catch {
      setMessage({ kind: 'error', text: '画像重算未完成，请稍后重试。' })
    } finally {
      setBusyId(null)
    }
  }

  return {
    memories,
    documents,
    summary,
    loading,
    busyId,
    confirmMemoryId,
    setConfirmMemoryId,
    confirmDocId,
    setConfirmDocId,
    confirmDanger,
    setConfirmDanger,
    message,
    handleDeleteMemory,
    handleDeleteDocument,
    handleDanger,
    handleRebuildIndexes,
    handleExport,
    handleRecompute,
    purgeDocumentsFn,
    purgeMemoryFn,
    deleteHistoryFn,
  }
}
