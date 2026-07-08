import { useEffect, useMemo, useRef, useState } from 'react';
import type { ClipboardEvent, DragEvent } from 'react';
import StudyHubAgentMessageList from './studyHubAgent/StudyHubAgentMessageList';
import {
  STUDYHUB_AGENT_POSITION_STORAGE_KEY,
  STUDYHUB_AGENT_STARTERS,
} from './studyHubAgent/constants';
import { useFloatingPanelPosition } from './studyHubAgent/useFloatingPanelPosition';
import { useStudyHubAgentChat } from './studyHubAgent/useStudyHubAgentChat';
import type { StudyHubAgentImageAttachment } from './studyHubAgent/types';

const AGENT_IMAGE_MAX_BYTES = 786_432;
const AGENT_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp']);

export default function HermesAgentWidget() {
  const [input, setInput] = useState('');
  const [imageAttachment, setImageAttachment] = useState<StudyHubAgentImageAttachment | null>(null);
  const [imageError, setImageError] = useState('');
  const listRef = useRef<HTMLDivElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const {
    open,
    closePanel,
    widgetRef,
    widgetStyle,
    startDrag,
    handlePointerMove,
    finishDrag,
  } = useFloatingPanelPosition({
    storageKey: STUDYHUB_AGENT_POSITION_STORAGE_KEY,
    closedWidth: 176,
    closedHeight: 58,
  });
  const {
    loading,
    thinkingStages,
    streamingAnswer,
    user,
    messages,
    materialDetails,
    submitQuery,
  } = useStudyHubAgentChat();

  useEffect(() => {
    if (!open || !listRef.current) return;
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, open, loading]);

  const hasConversation = useMemo(() => messages.length > 1, [messages.length]);

  const submitAndClear = (value: string, attachment: StudyHubAgentImageAttachment | null = imageAttachment) => {
    const query = value.trim();
    if ((!query && !attachment) || loading) return;
    setInput('');
    setImageAttachment(null);
    setImageError('');
    if (imageInputRef.current) {
      imageInputRef.current.value = '';
    }
    void submitQuery(query, attachment ? [attachment] : []);
  };

  const handleImageChange = (file: File | undefined) => {
    setImageError('');
    if (!file) return;
    if (!AGENT_IMAGE_TYPES.has(file.type)) {
      setImageError('仅支持 PNG、JPG 或 WEBP 图片');
      return;
    }
    if (file.size > AGENT_IMAGE_MAX_BYTES) {
      setImageError('图片不能超过 768KB');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = typeof reader.result === 'string' ? reader.result : '';
      if (!dataUrl) {
        setImageError('图片读取失败');
        return;
      }
      setImageAttachment({
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        name: file.name || '学习图片',
        mimeType: file.type,
        dataUrl,
        sizeBytes: file.size,
      });
    };
    reader.onerror = () => setImageError('图片读取失败');
    reader.readAsDataURL(file);
  };

  const handleImagePaste = (event: ClipboardEvent<HTMLFormElement>) => {
    const file = findImageFile(event.clipboardData.files);
    if (!file) return;
    event.preventDefault();
    handleImageChange(file);
  };

  const handleImageDrop = (event: DragEvent<HTMLFormElement>) => {
    const file = findImageFile(event.dataTransfer.files);
    if (!file) return;
    event.preventDefault();
    handleImageChange(file);
  };

  return (
    <section
      ref={widgetRef}
      className={`hermes-agent ${open ? 'is-open' : ''}`}
      style={widgetStyle}
      aria-label="StudyHub 学习辅导"
      onPointerMove={handlePointerMove}
      onPointerUp={finishDrag}
      onPointerCancel={finishDrag}
    >
      {!open ? (
        <button
          className="hermes-agent__launcher"
          type="button"
          aria-label="打开 StudyHub 学习辅导"
          onPointerDown={(event) => startDrag(event, 'launcher')}
        >
          <span className="hermes-agent__spark" aria-hidden="true" />
          <span>
            <strong>StudyHub</strong>
            <small>学习辅导</small>
          </span>
        </button>
      ) : (
        <div className="hermes-agent__panel">
          <div className="hermes-agent__header" onPointerDown={(event) => startDrag(event, 'header')}>
            <div>
              <span className="hermes-agent__eyebrow">StudyHub Agent</span>
              <h3>StudyHub 学习辅导</h3>
            </div>
            <button
              className="hermes-agent__close"
              type="button"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation();
                closePanel();
              }}
              aria-label="收起 StudyHub 学习辅导"
            >
              ×
            </button>
          </div>
          <div className="hermes-agent__status">
            <span className={user ? 'is-online' : 'is-offline'} />
            {user ? '已连接平台资料库' : '登录后可基于平台资料对话'}
          </div>
          <StudyHubAgentMessageList
            listRef={listRef}
            messages={messages}
            loading={loading}
            thinkingStages={thinkingStages}
            streamingAnswer={streamingAnswer}
            materialDetails={materialDetails}
            onFollowup={submitAndClear}
          />
          {!hasConversation && (
            <div className="hermes-agent__starters">
              {STUDYHUB_AGENT_STARTERS.map((item) => (
                <button key={item} type="button" onClick={() => submitAndClear(item)}>
                  {item}
                </button>
              ))}
            </div>
          )}
          <form
            className="hermes-agent__form"
            onPaste={handleImagePaste}
            onDragOver={(event) => {
              if (findImageFile(event.dataTransfer.files)) {
                event.preventDefault();
              }
            }}
            onDrop={handleImageDrop}
            onSubmit={(event) => {
              event.preventDefault();
              submitAndClear(input);
            }}
          >
            {(imageAttachment || imageError) && (
              <div className="hermes-agent__attachment-row">
                {imageAttachment && (
                  <div className="hermes-agent__attachment-preview">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    {imageAttachment.dataUrl && <img src={imageAttachment.dataUrl} alt={imageAttachment.name} />}
                    <span>{imageAttachment.name}</span>
                    <button
                      type="button"
                      onClick={() => {
                        setImageAttachment(null);
                        if (imageInputRef.current) {
                          imageInputRef.current.value = '';
                        }
                      }}
                    >
                      移除
                    </button>
                  </div>
                )}
                {imageError && <span className="hermes-agent__attachment-error">{imageError}</span>}
              </div>
            )}
            <button
              className="hermes-agent__image-button"
              type="button"
              disabled={loading}
              onClick={() => imageInputRef.current?.click()}
              aria-label="添加题目图片"
              title="添加题目图片"
            >
              图片
            </button>
            <input
              ref={imageInputRef}
              className="hermes-agent__file-input"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              disabled={loading}
              onChange={(event) => handleImageChange(event.target.files?.[0])}
            />
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="描述你要学什么、多久考试、哪里卡住"
              aria-label="StudyHub 学习辅导输入"
              disabled={loading}
            />
            <button type="submit" disabled={loading || (!input.trim() && !imageAttachment)}>
              发送
            </button>
          </form>
        </div>
      )}
    </section>
  );
}

function findImageFile(files: FileList | null) {
  if (!files) return undefined;
  return Array.from(files).find((file) => file.type.startsWith('image/'));
}
