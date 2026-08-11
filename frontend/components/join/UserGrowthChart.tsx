type GrowthPoint = {
  date: string;
  newUsers: number;
  totalUsers: number;
};

const USER_GROWTH_POINTS: GrowthPoint[] = [
  { date: '2025-11-22', newUsers: 8, totalUsers: 8 },
  { date: '2025-11-29', newUsers: 4, totalUsers: 12 },
  { date: '2025-12-06', newUsers: 72, totalUsers: 84 },
  { date: '2025-12-13', newUsers: 18, totalUsers: 102 },
  { date: '2025-12-20', newUsers: 17, totalUsers: 119 },
  { date: '2025-12-27', newUsers: 62, totalUsers: 181 },
  { date: '2026-01-03', newUsers: 45, totalUsers: 226 },
  { date: '2026-01-10', newUsers: 12, totalUsers: 238 },
  { date: '2026-01-17', newUsers: 1, totalUsers: 239 },
  { date: '2026-01-24', newUsers: 0, totalUsers: 239 },
  { date: '2026-01-31', newUsers: 0, totalUsers: 239 },
  { date: '2026-02-07', newUsers: 0, totalUsers: 239 },
  { date: '2026-02-14', newUsers: 0, totalUsers: 239 },
  { date: '2026-02-21', newUsers: 1, totalUsers: 240 },
  { date: '2026-02-28', newUsers: 2, totalUsers: 242 },
  { date: '2026-03-07', newUsers: 8, totalUsers: 250 },
  { date: '2026-03-14', newUsers: 2, totalUsers: 252 },
  { date: '2026-03-21', newUsers: 1, totalUsers: 253 },
  { date: '2026-03-28', newUsers: 0, totalUsers: 253 },
  { date: '2026-04-04', newUsers: 0, totalUsers: 253 },
  { date: '2026-04-11', newUsers: 2, totalUsers: 255 },
  { date: '2026-04-18', newUsers: 1, totalUsers: 256 },
  { date: '2026-04-25', newUsers: 15, totalUsers: 271 },
  { date: '2026-05-02', newUsers: 0, totalUsers: 271 },
  { date: '2026-05-09', newUsers: 8, totalUsers: 279 },
  { date: '2026-05-16', newUsers: 4, totalUsers: 283 },
  { date: '2026-05-23', newUsers: 0, totalUsers: 283 },
  { date: '2026-05-30', newUsers: 4, totalUsers: 287 },
  { date: '2026-06-06', newUsers: 4, totalUsers: 291 },
  { date: '2026-06-13', newUsers: 5, totalUsers: 296 },
  { date: '2026-06-20', newUsers: 10, totalUsers: 306 },
  { date: '2026-06-27', newUsers: 26, totalUsers: 332 },
  { date: '2026-07-04', newUsers: 13, totalUsers: 345 },
  { date: '2026-07-08', newUsers: 0, totalUsers: 345 },
];

const TOTAL_TICKS = [0, 100, 200, 300, 400];
const NEW_USER_TICKS = [0, 20, 40, 60, 80];
const DESKTOP_DATE_TICKS = [0, 5, 10, 15, 20, 25, 30, 33];
const MOBILE_DATE_TICKS = [0, 8, 16, 24, 33];

type GrowthPlotProps = {
  compact?: boolean;
};

function GrowthPlot({ compact = false }: GrowthPlotProps) {
  const width = compact ? 360 : 880;
  const height = compact ? 282 : 410;
  const margin = compact
    ? { left: 36, right: 34, top: 30, bottom: 44 }
    : { left: 62, right: 62, top: 38, bottom: 54 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const dateTicks = compact ? MOBILE_DATE_TICKS : DESKTOP_DATE_TICKS;
  const rightTicks = compact ? [0, 40, 80] : NEW_USER_TICKS;
  const barWidth = Math.max(compact ? 3 : 7, (plotWidth / USER_GROWTH_POINTS.length) * 0.58);

  const x = (index: number) => margin.left + (index / (USER_GROWTH_POINTS.length - 1)) * plotWidth;
  const totalY = (value: number) => margin.top + plotHeight - (value / 400) * plotHeight;
  const newUserY = (value: number) => margin.top + plotHeight - (value / 80) * plotHeight;
  const linePoints = USER_GROWTH_POINTS.map(
    (point, index) => `${x(index)},${totalY(point.totalUsers)}`
  ).join(' ');
  const areaPoints = `${margin.left},${margin.top + plotHeight} ${linePoints} ${margin.left + plotWidth},${
    margin.top + plotHeight
  }`;
  const lastPoint = USER_GROWTH_POINTS[USER_GROWTH_POINTS.length - 1];
  const lastX = x(USER_GROWTH_POINTS.length - 1);
  const lastY = totalY(lastPoint.totalUsers);

  return (
    <svg
      className={`join-growth-chart__svg join-growth-chart__svg--${compact ? 'mobile' : 'desktop'}`}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      focusable="false"
    >
      <text className="join-growth-chart__axis-title" x={margin.left} y={compact ? 13 : 18}>
        累计用户
      </text>
      <text
        className="join-growth-chart__axis-title"
        x={width - margin.right}
        y={compact ? 13 : 18}
        textAnchor="end"
      >
        周新增
      </text>

      {TOTAL_TICKS.map((tick) => {
        const y = totalY(tick);
        return (
          <g key={`total-${tick}`}>
            <line
              className="join-growth-chart__grid"
              x1={margin.left}
              x2={width - margin.right}
              y1={y}
              y2={y}
            />
            <text
              className="join-growth-chart__axis-label"
              x={margin.left - 9}
              y={y + 4}
              textAnchor="end"
            >
              {tick}
            </text>
          </g>
        );
      })}

      {rightTicks.map((tick) => (
        <text
          key={`new-${tick}`}
          className="join-growth-chart__axis-label join-growth-chart__axis-label--right"
          x={width - margin.right + 9}
          y={newUserY(tick) + 4}
        >
          {tick}
        </text>
      ))}

      {USER_GROWTH_POINTS.map((point, index) => {
        const top = newUserY(point.newUsers);
        const barHeight = margin.top + plotHeight - top;
        return (
          <rect
            key={point.date}
            className="join-growth-chart__bar"
            x={x(index) - barWidth / 2}
            y={top}
            width={barWidth}
            height={barHeight}
            rx={Math.min(2.5, barWidth / 2)}
          >
            <title>{`${point.date}：本周新增 ${point.newUsers} 人，累计 ${point.totalUsers} 人`}</title>
          </rect>
        );
      })}

      <polygon className="join-growth-chart__area" points={areaPoints} />
      <polyline className="join-growth-chart__line" points={linePoints} />

      {dateTicks.map((index) => {
        const point = USER_GROWTH_POINTS[index];
        return (
          <g key={`date-${point.date}`}>
            <line
              className="join-growth-chart__tick"
              x1={x(index)}
              x2={x(index)}
              y1={margin.top + plotHeight}
              y2={margin.top + plotHeight + 5}
            />
            <text
              className="join-growth-chart__date-label"
              x={x(index)}
              y={margin.top + plotHeight + (compact ? 22 : 26)}
              textAnchor="middle"
            >
              {point.date.slice(2, 7).replace('-', '.')}
            </text>
          </g>
        );
      })}

      <circle className="join-growth-chart__end-ring" cx={lastX} cy={lastY} r={compact ? 5 : 6} />
      <circle className="join-growth-chart__end-dot" cx={lastX} cy={lastY} r={compact ? 2.5 : 3} />
      <text
        className="join-growth-chart__end-label"
        x={lastX - (compact ? 7 : 10)}
        y={lastY - (compact ? 10 : 13)}
        textAnchor="end"
      >
        345
      </text>
    </svg>
  );
}

export default function UserGrowthChart() {
  return (
    <div className="join-growth-chart">
      <div className="join-growth-chart__intro">
        <div>
          <p className="join-growth-chart__lead">
            从首批用户到稳定增长，每一次注册都代表一份真实的校园连接。
          </p>
          <p className="join-growth-chart__period">统计区间：2025.11.16 - 2026.07.08</p>
        </div>
        <div className="join-growth-chart__legend" aria-label="图例">
          <span>
            <i className="join-growth-chart__legend-line" />
            累计用户
          </span>
          <span>
            <i className="join-growth-chart__legend-bar" />
            周期新增
          </span>
        </div>
      </div>

      <div className="join-growth-chart__stats" aria-label="用户增长摘要">
        <div>
          <strong>345</strong>
          <span>累计用户</span>
        </div>
        <div>
          <strong>235</strong>
          <span>统计天数</span>
        </div>
        <div>
          <strong>30</strong>
          <span>单日新增峰值</span>
        </div>
      </div>

      <div
        className="join-growth-chart__plot"
        role="img"
        aria-label="StudyHub 用户增长趋势图。2025年11月16日至2026年7月8日，累计用户增长至345人。"
      >
        <GrowthPlot />
        <GrowthPlot compact />
      </div>
      <p className="join-growth-chart__source">
        数据截至 2026.07.08，折线为累计用户，柱形按周汇总新增用户。
      </p>
    </div>
  );
}
