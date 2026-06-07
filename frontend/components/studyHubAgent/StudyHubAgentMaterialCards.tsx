import Link from 'next/link';
import { materialPath } from '../../lib/slug';
import { StudyHubAgentMaterialDetails, StudyHubAgentRecommendation } from './types';

interface StudyHubAgentMaterialCardsProps {
  recommendations: StudyHubAgentRecommendation[];
  materialDetails: StudyHubAgentMaterialDetails;
}

export default function StudyHubAgentMaterialCards({
  recommendations,
  materialDetails,
}: StudyHubAgentMaterialCardsProps) {
  if (recommendations.length === 0) return null;
  return (
    <div className="hermes-agent__materials">
      {recommendations.map((item) => {
        const detail = materialDetails[item.materialId];
        const title = detail?.title || item.title || `资料 #${item.materialId}`;
        const tags = detail?.tags || item.tags || [];
        return (
          <Link
            key={item.materialId}
            className="hermes-agent__material"
            href={materialPath(item.materialId, title)}
          >
            <strong>{title}</strong>
            <span>{item.reason || item.summary || '来自 StudyHub 资料库的候选内容'}</span>
            {tags.length > 0 && <em>{tags.slice(0, 3).join(' / ')}</em>}
          </Link>
        );
      })}
    </div>
  );
}
