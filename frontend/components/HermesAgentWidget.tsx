import { useEffect, useMemo, useRef, useState } from 'react';
import StudyHubAgentMessageList from './studyHubAgent/StudyHubAgentMessageList';
import {
  STUDYHUB_AGENT_POSITION_STORAGE_KEY,
  STUDYHUB_AGENT_STARTERS,
} from './studyHubAgent/constants';
import { useFloatingPanelPosition } from './studyHubAgent/useFloatingPanelPosition';
import { useStudyHubAgentChat } from './studyHubAgent/useStudyHubAgentChat';

export default function HermesAgentWidget() {
  const [input, setInput] = useState('');
  const listRef = useRef<HTMLDivElement>(null);
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

  const submitAndClear = (value: string) => {
    const query = value.trim();
    if (!query || loading) return;
    setInput('');
    void submitQuery(query);
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
            onSubmit={(event) => {
              event.preventDefault();
              submitAndClear(input);
            }}
          >
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="描述你要学什么、多久考试、哪里卡住"
              aria-label="StudyHub 学习辅导输入"
              disabled={loading}
            />
            <button type="submit" disabled={loading || !input.trim()}>
              发送
            </button>
          </form>
        </div>
      )}
    </section>
  );
}
