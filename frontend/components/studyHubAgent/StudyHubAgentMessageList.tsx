import { RefObject } from 'react';
import SafeMarkdown from '../SafeMarkdown';
import StudyHubAgentMaterialCards from './StudyHubAgentMaterialCards';
import { StudyHubAgentMaterialDetails, StudyHubAgentMessage } from './types';

interface StudyHubAgentMessageListProps {
  listRef: RefObject<HTMLDivElement>;
  messages: StudyHubAgentMessage[];
  loading: boolean;
  thinkingStages: string[];
  materialDetails: StudyHubAgentMaterialDetails;
  onFollowup: (value: string) => void;
}

export default function StudyHubAgentMessageList({
  listRef,
  messages,
  loading,
  thinkingStages,
  materialDetails,
  onFollowup,
}: StudyHubAgentMessageListProps) {
  const stages = thinkingStages.length > 0 ? thinkingStages : ['理解问题', '检索资料', '整理答案'];
  return (
    <div className="hermes-agent__messages" ref={listRef} role="log" aria-live="polite" aria-relevant="additions">
      {messages.map((message) => (
        <article key={message.id} className={`hermes-agent__message hermes-agent__message--${message.role}`}>
          <div className="hermes-agent__markdown">
            <SafeMarkdown>{message.content}</SafeMarkdown>
          </div>
          {message.imageAttachments && message.imageAttachments.length > 0 && (
            <div className="hermes-agent__message-images">
              {message.imageAttachments.slice(0, 1).map((item) => (
                item.dataUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img key={item.id} src={item.dataUrl} alt={item.name || '学习图片'} />
                ) : (
                  <span key={item.id}>{item.name || '学习图片'}</span>
                )
              ))}
            </div>
          )}
          {message.recommendations && message.recommendations.length > 0 && (
            <StudyHubAgentMaterialCards
              recommendations={message.recommendations}
              materialDetails={materialDetails}
            />
          )}
          {message.followups && message.followups.length > 0 && (
            <div className="hermes-agent__followups">
              {message.followups.slice(0, 3).map((item) => (
                <button key={item} type="button" onClick={() => onFollowup(item)}>
                  {item}
                </button>
              ))}
            </div>
          )}
        </article>
      ))}
      {loading && (
        <article
          className="hermes-agent__message hermes-agent__message--assistant hermes-agent__message--thinking"
          aria-label="StudyHub 正在思考"
        >
          <div className="hermes-agent__thinking">
            <span className="hermes-agent__thinking-orb" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
            <div className="hermes-agent__thinking-copy">
              <p>StudyHub 正在思考</p>
              <div className="hermes-agent__thinking-steps" aria-hidden="true">
                {stages.slice(-6).map((stage) => (
                  <span key={stage}>{stage}</span>
                ))}
              </div>
            </div>
          </div>
        </article>
      )}
    </div>
  );
}
