export default function ContextSection({ t, form, setForm }) {
    const context = form.context || {}
    return (
        <div className="bg-card border border-border rounded-xl p-5 space-y-4">
            <h3 className="font-semibold">{t('settings.contextTitle')}</h3>
            <label className="flex items-start gap-3 rounded-lg border border-border bg-background/60 p-4">
                <input
                    type="checkbox"
                    checked={Boolean(context.fresh_conversation ?? true)}
                    onChange={(e) => setForm((prev) => ({
                        ...prev,
                        context: { ...prev.context, fresh_conversation: e.target.checked },
                    }))}
                    className="mt-1 h-4 w-4 rounded border-border"
                />
                <div className="space-y-1">
                    <span className="text-sm font-medium block">{t('settings.freshConversation')}</span>
                    <span className="text-xs text-muted-foreground block">{t('settings.freshConversationDesc')}</span>
                </div>
            </label>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <label className="text-sm space-y-2">
                    <span className="text-muted-foreground">{t('settings.maxChars')}</span>
                    <input
                        type="number"
                        min={1000}
                        value={context.max_chars ?? 12000}
                        onChange={(e) => setForm((prev) => ({
                            ...prev,
                            context: { ...prev.context, max_chars: Number(e.target.value || 12000) },
                        }))}
                        className="w-full bg-background border border-border rounded-lg px-3 py-2"
                    />
                </label>
                <label className="text-sm space-y-2">
                    <span className="text-muted-foreground">{t('settings.maxMessages')}</span>
                    <input
                        type="number"
                        min={1}
                        value={context.max_messages ?? 16}
                        onChange={(e) => setForm((prev) => ({
                            ...prev,
                            context: { ...prev.context, max_messages: Number(e.target.value || 16) },
                        }))}
                        className="w-full bg-background border border-border rounded-lg px-3 py-2"
                    />
                </label>
                <label className="text-sm space-y-2">
                    <span className="text-muted-foreground">{t('settings.maxMessageChars')}</span>
                    <input
                        type="number"
                        min={100}
                        value={context.max_message_chars ?? 2000}
                        onChange={(e) => setForm((prev) => ({
                            ...prev,
                            context: { ...prev.context, max_message_chars: Number(e.target.value || 2000) },
                        }))}
                        className="w-full bg-background border border-border rounded-lg px-3 py-2"
                    />
                </label>
            </div>
        </div>
    )
}
