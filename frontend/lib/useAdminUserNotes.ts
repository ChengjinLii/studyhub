import { useState } from 'react';

type NoteAlert = { type: 'success' | 'error'; text: string };

interface AdminUserNote {
  id: number;
  adminUsername?: string | null;
  adminNickname?: string | null;
  message: string;
  createdAt: string;
}

export const useAdminUserNotes = () => {
  const [noteDrafts, setNoteDrafts] = useState<Record<number, string>>({});
  const [noteAlerts, setNoteAlerts] = useState<Record<number, NoteAlert>>({});
  const [userNotes, setUserNotes] = useState<Record<number, AdminUserNote[]>>({});
  const [notesLoading, setNotesLoading] = useState<Record<number, boolean>>({});
  const [notePanelOpen, setNotePanelOpen] = useState<Record<number, boolean>>({});

  const loadUserNotes = async (userId: number) => {
    setNotesLoading((prev) => ({ ...prev, [userId]: true }));
    const resp = await fetch(`/api/admin/user-notes?userId=${userId}`);
    const json = await resp.json();
    if (resp.ok && json.ok) {
      setUserNotes((prev) => ({ ...prev, [userId]: json.data || [] }));
    }
    setNotesLoading((prev) => ({ ...prev, [userId]: false }));
  };

  const toggleNotePanel = async (userId: number) => {
    setNotePanelOpen((prev) => ({ ...prev, [userId]: !prev[userId] }));
    const willOpen = !notePanelOpen[userId];
    if (willOpen) {
      await loadUserNotes(userId);
    }
  };

  const handleSendNote = async (userId: number) => {
    const messageText = noteDrafts[userId]?.trim();
    if (!messageText) {
      setNoteAlerts((prev) => ({ ...prev, [userId]: { type: 'error', text: '留言不能为空' } }));
      return;
    }
    setNoteAlerts((prev) => ({ ...prev, [userId]: { type: 'success', text: '发送中...' } }));
    const resp = await fetch(`/api/admin/user-notes?userId=${userId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: messageText }),
    });
    const json = await resp.json();
    if (!resp.ok || !json.ok) {
      setNoteAlerts((prev) => ({ ...prev, [userId]: { type: 'error', text: json.msg || '发送失败' } }));
      return;
    }
    setNoteDrafts((prev) => ({ ...prev, [userId]: '' }));
    setNoteAlerts((prev) => ({ ...prev, [userId]: { type: 'success', text: '留言已发送' } }));
    await loadUserNotes(userId);
  };

  return {
    noteDrafts,
    setNoteDrafts,
    noteAlerts,
    userNotes,
    notesLoading,
    notePanelOpen,
    toggleNotePanel,
    handleSendNote,
  };
};
