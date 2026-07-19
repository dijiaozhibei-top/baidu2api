import { useEffect, useState } from 'react'
import { Check, ChevronDown, Copy, Cookie, Key, Plus, Save, Trash2 } from 'lucide-react'
import clsx from 'clsx'

import { useI18n } from '../../i18n'
import { maskSecret } from '../../utils/maskSecret'

function fallbackCopyText(text) {
    const textArea = document.createElement('textarea')
    textArea.value = text
    textArea.setAttribute('readonly', '')
    textArea.style.position = 'fixed'
    textArea.style.top = '-9999px'
    document.body.appendChild(textArea)
    textArea.focus()
    textArea.select()
    try {
        document.execCommand('copy')
    } finally {
        document.body.removeChild(textArea)
    }
}

export default function ConfigContainer({ config, onRefresh, onMessage, authFetch }) {
    const { t } = useI18n()
    const [cookiesText, setCookiesText] = useState(() => (config?.cookies || []).join('\n\n'))
    const [savingCookies, setSavingCookies] = useState(false)
    const [newKey, setNewKey] = useState('')
    const [keysExpanded, setKeysExpanded] = useState(true)
    const [copiedKey, setCopiedKey] = useState(null)
    const [busyKey, setBusyKey] = useState(null)

    
    useEffect(() => {
        setCookiesText((config?.cookies || []).join('\n\n'))
    }, [config])

    const keys = config?.keys || []

    const saveCookies = async () => {
        setSavingCookies(true)
        try {
            const values = cookiesText
                .split(/\n\s*\n|\n/)
                .map(s => s.trim())
                .filter(Boolean)
            const res = await authFetch('/admin/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cookies: { values } }),
            })
            const data = await res.json()
            if (!res.ok) {
                onMessage('error', data.detail || t('config.saveCookiesFailed'))
                return
            }
            onMessage('success', t('config.saveCookiesSuccess'))
            onRefresh?.()
        } catch (e) {
            onMessage('error', e.message)
        } finally {
            setSavingCookies(false)
        }
    }

    const addKey = async () => {
        setBusyKey('add')
        try {
            const res = await authFetch('/admin/keys', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(newKey.trim() ? { key: newKey.trim() } : {}),
            })
            const data = await res.json()
            if (!res.ok) {
                onMessage('error', data.detail || t('messages.failedToAdd'))
                return
            }
            setNewKey('')
            onMessage('success', t('config.addKeySuccess', { key: data.key || '' }))
            onRefresh?.()
        } catch (e) {
            onMessage('error', e.message)
        } finally {
            setBusyKey(null)
        }
    }

    const deleteKey = async (key) => {
        if (!window.confirm(t('config.confirmDeleteKey'))) return
        setBusyKey(key)
        try {
            const res = await authFetch(`/admin/keys/${encodeURIComponent(key)}`, { method: 'DELETE' })
            if (!res.ok) {
                const data = await res.json().catch(() => ({}))
                onMessage('error', data.detail || t('messages.deleteFailed'))
                return
            }
            onMessage('success', t('messages.deleted'))
            onRefresh?.()
        } catch (e) {
            onMessage('error', e.message)
        } finally {
            setBusyKey(null)
        }
    }

    const copyKey = async (key) => {
        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(key)
            } else {
                fallbackCopyText(key)
            }
            setCopiedKey(key)
            setTimeout(() => setCopiedKey(null), 1500)
        } catch {
            try {
                fallbackCopyText(key)
                setCopiedKey(key)
                setTimeout(() => setCopiedKey(null), 1500)
            } catch {
                onMessage('error', t('messages.copyFailed'))
            }
        }
    }

    return (
        <div className="space-y-6">
            <div className="bg-card border border-border rounded-xl p-5 space-y-4 shadow-sm">
                <div className="flex items-center gap-2">
                    <Cookie className="w-4 h-4 text-primary" />
                    <h3 className="font-semibold">{t('config.cookiesTitle')}</h3>
                </div>
                <p className="text-sm text-muted-foreground">{t('config.cookiesHelp')}</p>
                <textarea
                    rows={8}
                    value={cookiesText}
                    onChange={(e) => setCookiesText(e.target.value)}
                    placeholder={t('config.cookiesPlaceholder')}
                    className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm font-mono resize-y min-h-40"
                />
                <div className="flex justify-end">
                    <button
                        type="button"
                        onClick={saveCookies}
                        disabled={savingCookies}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50"
                    >
                        <Save className="w-4 h-4" />
                        {savingCookies ? t('actions.loading') : t('config.saveCookies')}
                    </button>
                </div>
            </div>

            <div className="bg-card border border-border rounded-xl overflow-hidden shadow-sm">
                <div
                    className="p-5 flex items-center justify-between cursor-pointer hover:bg-muted/40 transition-colors"
                    onClick={() => setKeysExpanded(!keysExpanded)}
                >
                    <div className="flex items-center gap-2">
                        <ChevronDown className={clsx('w-4 h-4 text-muted-foreground transition-transform', !keysExpanded && '-rotate-90')} />
                        <Key className="w-4 h-4 text-primary" />
                        <h3 className="font-semibold">{t('config.keysTitle')}</h3>
                        <span className="text-xs text-muted-foreground">({keys.length})</span>
                    </div>
                </div>
                {keysExpanded && (
                    <div className="px-5 pb-5 space-y-4 border-t border-border pt-4">
                        <p className="text-sm text-muted-foreground">{t('config.keysHelp')}</p>
                        <div className="flex flex-col sm:flex-row gap-2">
                            <input
                                value={newKey}
                                onChange={(e) => setNewKey(e.target.value)}
                                placeholder={t('config.keyPlaceholder')}
                                className="flex-1 bg-background border border-border rounded-lg px-3 py-2 text-sm font-mono"
                            />
                            <button
                                type="button"
                                onClick={addKey}
                                disabled={busyKey === 'add'}
                                className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50"
                            >
                                <Plus className="w-4 h-4" />
                                {t('config.addKey')}
                            </button>
                        </div>
                        <div className="space-y-2">
                            {keys.length === 0 && (
                                <div className="text-sm text-muted-foreground border border-dashed border-border rounded-lg p-4">
                                    {t('config.noKeys')}
                                </div>
                            )}
                            {keys.map((key) => (
                                <div key={key} className="flex items-center gap-2 border border-border rounded-lg px-3 py-2 bg-background">
                                    <code className="flex-1 text-xs font-mono truncate">{maskSecret(key)}</code>
                                    <button
                                        type="button"
                                        onClick={() => copyKey(key)}
                                        className="p-1.5 rounded-md hover:bg-muted text-muted-foreground"
                                        title={t('actions.copy')}
                                    >
                                        {copiedKey === key ? <Check className="w-4 h-4 text-emerald-600" /> : <Copy className="w-4 h-4" />}
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => deleteKey(key)}
                                        disabled={busyKey === key}
                                        className="p-1.5 rounded-md hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
                                        title={t('actions.delete')}
                                    >
                                        <Trash2 className="w-4 h-4" />
                                    </button>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
