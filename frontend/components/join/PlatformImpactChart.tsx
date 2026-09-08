import { useState } from 'react';

type MetricKey = 'users' | 'materials' | 'downloads';

type TrendMetric = {
  label: string;
  newLabel: string;
  unit: string;
  totalMax: number;
  newMax: number;
  values: number[];
};

const SNAPSHOT_DATE = '2026.09.08';

const TREND_METRICS: Record<MetricKey, TrendMetric> = {
  users: {
    label: '累计用户',
    newLabel: '每周新增用户',
    unit: '人',
    totalMax: 400,
    newMax: 80,
    values: [
      8, 4, 72, 18, 17, 62, 45, 12, 1, 0, 0, 0, 0, 1, 2, 8, 2, 1, 0, 0, 2, 1, 15, 0, 8, 4, 0, 4, 4,
      5, 10, 26, 13, 0, 0, 0, 0, 3, 2, 2, 2, 6, 2,
    ],
  },
  materials: {
    label: '累计资料',
    newLabel: '每周新增资料',
    unit: '份',
    totalMax: 200,
    newMax: 80,
    values: [
      0, 39, 69, 0, 6, 22, 11, 6, 1, 0, 6, 0, 0, 0, 0, 5, 1, 0, 2, 0, 0, 0, 1, 0, 0, 0, 2, 0, 1, 1,
      5, 1, 4, 0, 0, 0, 6, 1, 0, 0, 0, 0, 0,
    ],
  },
  downloads: {
    label: '累计下载',
    newLabel: '每周新增下载',
    unit: '次',
    totalMax: 1800,
    newMax: 300,
    values: [
      0, 7, 272, 87, 112, 214, 209, 53, 6, 4, 14, 2, 0, 1, 12, 75, 20, 2, 2, 12, 9, 7, 37, 1, 23,
      46, 5, 50, 41, 45, 87, 76, 93, 12, 1, 0, 15, 19, 8, 22, 14, 44, 19,
    ],
  },
};

const WEEK_DATES = Array.from({ length: 43 }, (_, index) => {
  const date = new Date(Date.UTC(2025, 10, 16 + index * 7));
  return date.toISOString().slice(0, 10);
});

const WEEKDAY_COUNTS = [348, 235, 274, 250, 195, 226, 250];
const WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
const HOUR_VALUES = [
  64, 18, 6, 17, 7, 1, 2, 5, 20, 39, 105, 120, 59, 102, 116, 139, 154, 163, 102, 127, 126, 115, 112,
  59,
];
const MONTHLY_ACTIVITY = [
  { month: '25.11', active: 4, returning: 0 },
  { month: '25.12', active: 176, returning: 0.6 },
  { month: '26.01', active: 73, returning: 52.1 },
  { month: '26.02', active: 8, returning: 75 },
  { month: '26.03', active: 34, returning: 79.4 },
  { month: '26.04', active: 35, returning: 51.4 },
  { month: '26.05', active: 61, returning: 73.8 },
  { month: '26.06', active: 137, returning: 59.1 },
  { month: '26.07', active: 33, returning: 87.9 },
  { month: '26.08', active: 21, returning: 61.9 },
  { month: '26.09', active: 12, returning: 50 },
];

const numberFormat = new Intl.NumberFormat('zh-CN');

function sum(values: number[]) {
  return values.reduce((total, value) => total + value, 0);
}

function TrendPlot({ metricKey, compact = false }: { metricKey: MetricKey; compact?: boolean }) {
  const metric = TREND_METRICS[metricKey];
  const totals: number[] = [];
  metric.values.reduce((total, value) => {
    const next = total + value;
    totals.push(next);
    return next;
  }, 0);

  const width = compact ? 460 : 880;
  const height = compact ? 270 : 330;
  const margin = compact
    ? { left: 42, right: 40, top: 36, bottom: 44 }
    : { left: 58, right: 58, top: 38, bottom: 50 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const base = margin.top + plotHeight;
  const x = (index: number) => margin.left + (index / (totals.length - 1)) * plotWidth;
  const totalY = (value: number) => base - (value / metric.totalMax) * plotHeight;
  const newY = (value: number) => base - (value / metric.newMax) * plotHeight;
  const barWidth = Math.max(compact ? 3 : 5, (plotWidth / totals.length) * 0.56);
  const totalTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => ratio * metric.totalMax);
  const newTicks = [0, 0.5, 1].map((ratio) => ratio * metric.newMax);
  const dateTicks = compact ? [0, 10, 21, 32, 42] : [0, 7, 14, 21, 28, 35, 42];
  const linePoints = totals.map((value, index) => `${x(index)},${totalY(value)}`).join(' ');
  const areaPoints = `${margin.left},${base} ${linePoints} ${margin.left + plotWidth},${base}`;
  const lastIndex = totals.length - 1;

  return (
    <svg
      className={`join-growth-chart__svg join-growth-chart__svg--${compact ? 'mobile' : 'desktop'}`}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      focusable="false"
    >
      {totalTicks.map((tick) => (
        <g key={`total-${tick}`}>
          <line
            className="join-growth-chart__grid"
            x1={margin.left}
            x2={width - margin.right}
            y1={totalY(tick)}
            y2={totalY(tick)}
          />
          <text
            className="join-growth-chart__axis-label"
            x={margin.left - 10}
            y={totalY(tick) + 4}
            textAnchor="end"
          >
            {numberFormat.format(tick)}
          </text>
        </g>
      ))}
      {newTicks.map((tick) => (
        <text
          key={`new-${tick}`}
          className="join-growth-chart__axis-label join-growth-chart__axis-label--right"
          x={width - margin.right + 10}
          y={newY(tick) + 4}
        >
          {numberFormat.format(tick)}
        </text>
      ))}
      {metric.values.map((value, index) => (
        <rect
          key={WEEK_DATES[index]}
          className="join-growth-chart__bar"
          x={x(index) - barWidth / 2}
          y={newY(value)}
          width={barWidth}
          height={base - newY(value)}
          rx={2}
        >
          <title>{`${WEEK_DATES[index]}：新增${value}${metric.unit}，累计${totals[index]}${metric.unit}`}</title>
        </rect>
      ))}
      <polygon className="join-growth-chart__area" points={areaPoints} />
      <polyline className="join-growth-chart__line" points={linePoints} />
      {dateTicks.map((index) => (
        <text
          key={WEEK_DATES[index]}
          className="join-growth-chart__date-label"
          x={x(index)}
          y={base + 28}
          textAnchor="middle"
        >
          {WEEK_DATES[index].slice(2, 7).replace('-', '.')}
        </text>
      ))}
      <circle
        className="join-growth-chart__end-ring"
        cx={x(lastIndex)}
        cy={totalY(totals[lastIndex])}
        r={5}
      />
      <circle
        className="join-growth-chart__end-dot"
        cx={x(lastIndex)}
        cy={totalY(totals[lastIndex])}
        r={2.5}
      />
      <text
        className="join-growth-chart__end-label"
        x={x(lastIndex) - 9}
        y={totalY(totals[lastIndex]) - 12}
        textAnchor="end"
      >
        {numberFormat.format(totals[lastIndex])}
      </text>
    </svg>
  );
}

function WeekdayPlot({ compact = false }: { compact?: boolean }) {
  const width = compact ? 460 : 880;
  const height = compact ? 250 : 275;
  const margin = compact
    ? { left: 42, right: 18, top: 30, bottom: 42 }
    : { left: 52, right: 24, top: 30, bottom: 44 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const base = margin.top + plotHeight;
  const total = sum(WEEKDAY_COUNTS);
  const shares = WEEKDAY_COUNTS.map((value) => (value / total) * 100);
  const x = (index: number) => margin.left + (index / 6) * plotWidth;
  const y = (value: number) => base - (value / 20) * plotHeight;
  const linePoints = shares.map((value, index) => `${x(index)},${y(value)}`).join(' ');
  const areaPoints = `${margin.left},${base} ${linePoints} ${margin.left + plotWidth},${base}`;
  const ticks = compact ? [0, 10, 20] : [0, 5, 10, 15, 20];

  return (
    <svg
      className={`join-growth-chart__svg join-growth-chart__svg--${compact ? 'mobile' : 'desktop'}`}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      focusable="false"
    >
      {ticks.map((tick) => (
        <g key={tick}>
          <line
            className="join-growth-chart__grid"
            x1={margin.left}
            x2={width - margin.right}
            y1={y(tick)}
            y2={y(tick)}
          />
          <text
            className="join-growth-chart__axis-label"
            x={margin.left - 10}
            y={y(tick) + 4}
            textAnchor="end"
          >
            {tick}%
          </text>
        </g>
      ))}
      <polygon className="join-growth-chart__area" points={areaPoints} />
      <line
        className="join-impact-chart__average"
        x1={margin.left}
        x2={width - margin.right}
        y1={y(100 / 7)}
        y2={y(100 / 7)}
      />
      <polyline className="join-growth-chart__line" points={linePoints} />
      {shares.map((share, index) => (
        <g key={WEEKDAY_NAMES[index]}>
          <title>{`${WEEKDAY_NAMES[index]}：${share.toFixed(1)}%，${WEEKDAY_COUNTS[index]}次`}</title>
          <circle
            className={index === 0 ? 'join-impact-chart__peak' : 'join-growth-chart__end-dot'}
            cx={x(index)}
            cy={y(share)}
            r={index === 0 ? 5 : 4}
          />
          <text
            className="join-growth-chart__end-label"
            x={x(index)}
            y={y(share) - 13}
            textAnchor="middle"
          >
            {share.toFixed(1)}%
          </text>
          <text
            className="join-growth-chart__date-label"
            x={x(index)}
            y={base + 28}
            textAnchor="middle"
          >
            {WEEKDAY_NAMES[index]}
          </text>
        </g>
      ))}
    </svg>
  );
}

function ActivityPlot({ compact = false }: { compact?: boolean }) {
  const width = compact ? 460 : 880;
  const height = compact ? 270 : 320;
  const margin = compact
    ? { left: 42, right: 42, top: 28, bottom: 46 }
    : { left: 55, right: 55, top: 32, bottom: 50 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const base = margin.top + plotHeight;
  const x = (index: number) => margin.left + (index / (MONTHLY_ACTIVITY.length - 1)) * plotWidth;
  const activeY = (value: number) => base - (value / 180) * plotHeight;
  const returningY = (value: number) => base - (value / 100) * plotHeight;
  const barWidth = Math.max(compact ? 10 : 16, (plotWidth / MONTHLY_ACTIVITY.length) * 0.38);
  const linePoints = MONTHLY_ACTIVITY.map(
    (point, index) => `${x(index)},${returningY(point.returning)}`
  ).join(' ');
  const areaPoints = `${margin.left},${base} ${linePoints} ${margin.left + plotWidth},${base}`;

  return (
    <svg
      className={`join-growth-chart__svg join-growth-chart__svg--${compact ? 'mobile' : 'desktop'}`}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      focusable="false"
    >
      {[0, 60, 120, 180].map((tick) => (
        <g key={`active-${tick}`}>
          <line
            className="join-growth-chart__grid"
            x1={margin.left}
            x2={width - margin.right}
            y1={activeY(tick)}
            y2={activeY(tick)}
          />
          <text
            className="join-growth-chart__axis-label"
            x={margin.left - 10}
            y={activeY(tick) + 4}
            textAnchor="end"
          >
            {tick}
          </text>
        </g>
      ))}
      {[0, 50, 100].map((tick) => (
        <text
          key={`returning-${tick}`}
          className="join-growth-chart__axis-label join-growth-chart__axis-label--right"
          x={width - margin.right + 10}
          y={returningY(tick) + 4}
        >
          {tick}%
        </text>
      ))}
      {MONTHLY_ACTIVITY.map((point, index) => (
        <rect
          key={point.month}
          className="join-growth-chart__bar"
          x={x(index) - barWidth / 2}
          y={activeY(point.active)}
          width={barWidth}
          height={base - activeY(point.active)}
          rx={2}
        >
          <title>{`${point.month}：${point.active}位月活跃用户`}</title>
        </rect>
      ))}
      <polygon className="join-growth-chart__area" points={areaPoints} />
      <polyline className="join-growth-chart__line" points={linePoints} />
      {MONTHLY_ACTIVITY.map((point, index) => (
        <g key={`point-${point.month}`}>
          <circle
            className="join-impact-chart__activity-point"
            cx={x(index)}
            cy={returningY(point.returning)}
            r={3.5}
          >
            <title>{`${point.month}：回访用户占比${point.returning}%`}</title>
          </circle>
          {(!compact || index % 2 === 0) && (
            <text
              className="join-growth-chart__date-label"
              x={x(index)}
              y={base + 28}
              textAnchor="middle"
            >
              {point.month}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}

function RingMetric({
  percentage,
  children,
  accent = false,
}: {
  percentage: number;
  children: React.ReactNode;
  accent?: boolean;
}) {
  const circumference = 157.08;
  const filled = (percentage / 100) * circumference;
  return (
    <div
      className={`join-impact-chart__ring-item${accent ? ' join-impact-chart__ring-item--accent' : ''}`}
    >
      <svg className="join-impact-chart__ring" viewBox="0 0 64 64" aria-hidden="true">
        <circle className="join-impact-chart__ring-track" cx="32" cy="32" r="25" />
        <circle
          className="join-impact-chart__ring-value"
          cx="32"
          cy="32"
          r="25"
          strokeDasharray={`${filled} ${circumference - filled}`}
        />
      </svg>
      <div>
        <strong>{percentage}%</strong>
        <span>{children}</span>
      </div>
    </div>
  );
}

export default function PlatformImpactChart() {
  const [metricKey, setMetricKey] = useState<MetricKey>('users');
  const metric = TREND_METRICS[metricKey];
  const currentTotal = sum(metric.values);
  const hourTotal = sum(HOUR_VALUES);
  const peakHour = HOUR_VALUES.indexOf(Math.max(...HOUR_VALUES));

  return (
    <div className="join-growth-chart join-impact-chart">
      <div className="join-growth-chart__intro">
        <p className="join-growth-chart__period">累计数据截至 {SNAPSHOT_DATE}</p>
        <span className="join-impact-chart__status">真实业务记录</span>
      </div>

      <div className="join-growth-chart__stats join-impact-chart__stats" aria-label="平台累计成果">
        <div>
          <strong>362</strong>
          <span>累计用户</span>
        </div>
        <div>
          <strong>190</strong>
          <span>上架资料</span>
        </div>
        <div>
          <strong>1,778</strong>
          <span>累计下载</span>
        </div>
        <div>
          <strong>20</strong>
          <span>投稿者</span>
        </div>
      </div>

      <section className="join-impact-chart__section" aria-labelledby="impact-trend-title">
        <div className="join-impact-chart__section-head">
          <div>
            <h3 id="impact-trend-title">累计发展趋势</h3>
            <p>折线显示累计规模，柱形显示每周新增</p>
          </div>
          <div className="join-impact-chart__tabs" role="tablist" aria-label="选择趋势指标">
            {(['users', 'materials', 'downloads'] as MetricKey[]).map((key) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={metricKey === key}
                onClick={() => setMetricKey(key)}
              >
                {{ users: '用户', materials: '资料', downloads: '下载' }[key]}
              </button>
            ))}
          </div>
        </div>
        <div className="join-impact-chart__meta">
          <div className="join-growth-chart__legend" aria-label="图例">
            <span>
              <i className="join-growth-chart__legend-line" />
              {metric.label}
            </span>
            <span>
              <i className="join-growth-chart__legend-bar" />
              {metric.newLabel}
            </span>
          </div>
          <span className="join-impact-chart__kpi">
            当前 <strong>{numberFormat.format(currentTotal)}</strong>
          </span>
        </div>
        <div
          className="join-growth-chart__plot"
          role="tabpanel"
          aria-label={`${metric.label}趋势图`}
        >
          <TrendPlot metricKey={metricKey} />
          <TrendPlot metricKey={metricKey} compact />
        </div>
        <p className="join-growth-chart__source">
          统计区间：2025.11.16 - {SNAPSHOT_DATE}，按周汇总。
        </p>
      </section>

      <section className="join-impact-chart__section" aria-labelledby="impact-weekday-title">
        <div className="join-impact-chart__section-head">
          <div>
            <h3 id="impact-weekday-title">资料获取的星期分布</h3>
            <p>统计期内全部首次获取记录按星期汇总，虚线为均衡基准 14.3%</p>
          </div>
          <span className="join-impact-chart__kpi">
            占比最高 <strong>周一 · 19.6%</strong>
          </span>
        </div>
        <div
          className="join-growth-chart__plot"
          role="img"
          aria-label="星期一至星期日的资料首次获取占比分布"
        >
          <WeekdayPlot />
          <WeekdayPlot compact />
        </div>
        <p className="join-growth-chart__source">
          百分比反映全部统计期分布，不代表单个自然周下载量。
        </p>
      </section>

      <section className="join-impact-chart__section" aria-labelledby="impact-hour-title">
        <div className="join-impact-chart__section-head">
          <div>
            <h3 id="impact-hour-title">一天中的资料获取时段</h3>
            <p>按北京时间汇总已记录的首次获取行为</p>
          </div>
          <span className="join-impact-chart__kpi">
            活跃峰值 <strong>{peakHour}:00</strong>
          </span>
        </div>
        <div
          className="join-impact-chart__hours"
          role="img"
          aria-label="24小时资料首次获取时段分布，17点为峰值"
        >
          <div className="join-impact-chart__hour-grid" aria-hidden="true">
            {[180, 120, 60, 0].map((tick) => (
              <span key={tick}>{tick}</span>
            ))}
          </div>
          <div className="join-impact-chart__hour-bars">
            {HOUR_VALUES.map((value, hour) => (
              <div
                key={hour}
                className="join-impact-chart__hour-item"
                data-label={hour % 3 === 0 ? String(hour).padStart(2, '0') : ''}
              >
                <span
                  className={hour === peakHour ? 'is-peak' : ''}
                  style={{ height: `${(value / 180) * 100}%` }}
                  title={`${String(hour).padStart(2, '0')}:00 - ${String(hour).padStart(2, '0')}:59：${value}次，占${((value / hourTotal) * 100).toFixed(1)}%`}
                />
              </div>
            ))}
          </div>
        </div>
        <p className="join-growth-chart__source">
          记录区间：2025.11.27 - {SNAPSHOT_DATE}，共1,778条首次获取记录。
        </p>
        <p className="join-impact-chart__note">
          同一用户首次获取同一份当前可见资料记为一条。累计下载、下载趋势、星期与时段分布采用同一明细记录口径。
        </p>
      </section>

      <section className="join-impact-chart__section" aria-labelledby="impact-activity-title">
        <div className="join-impact-chart__section-head">
          <div>
            <h3 id="impact-activity-title">月活跃与回访趋势</h3>
            <p>活跃用户是当月至少产生一次下载、投稿、点赞、评论或评分行为的普通账户</p>
          </div>
        </div>
        <div className="join-impact-chart__meta">
          <div className="join-growth-chart__legend" aria-label="图例">
            <span>
              <i className="join-growth-chart__legend-bar" />
              月活跃用户
            </span>
            <span>
              <i className="join-growth-chart__legend-line" />
              回访用户占比
            </span>
          </div>
          <span className="join-growth-chart__source">2026年9月为截至8日的不完整月份</span>
        </div>
        <div
          className="join-growth-chart__plot"
          role="img"
          aria-label="月活跃用户和回访用户占比趋势图"
        >
          <ActivityPlot />
          <ActivityPlot compact />
        </div>
      </section>

      <section className="join-impact-chart__section" aria-labelledby="impact-depth-title">
        <div className="join-impact-chart__section-head">
          <div>
            <h3 id="impact-depth-title">行为深度与内容使用</h3>
            <p>同时观察用户是否持续使用，以及资料是否真正产生获取记录</p>
          </div>
          <span className="join-impact-chart__kpi">
            跨月活跃 <strong>147人</strong>
          </span>
        </div>
        <div className="join-impact-chart__evidence">
          <div>
            <h4>独立下载用户深度</h4>
            <div className="join-impact-chart__depth-list">
              {[
                ['下载 ≥ 1份', 325, 100],
                ['下载 ≥ 2份', 237, 72.9],
                ['下载 ≥ 5份', 127, 39.1],
                ['下载 ≥ 10份', 47, 14.5],
              ].map(([label, value, width]) => (
                <div className="join-impact-chart__depth-row" key={String(label)}>
                  <span>{label}</span>
                  <i>
                    <b style={{ width: `${width}%` }} />
                  </i>
                  <strong>{value}</strong>
                </div>
              ))}
            </div>
            <div className="join-impact-chart__depth-summary">
              <div>
                <strong>3份</strong>
                <span>下载量中位数</span>
              </div>
              <div>
                <strong>5.4份</strong>
                <span>人均下载量</span>
              </div>
            </div>
          </div>
          <div className="join-impact-chart__content-evidence">
            <h4>内容使用证据</h4>
            <div className="join-impact-chart__ring-list">
              <RingMetric percentage={90.5}>172 / 190份资料产生过真实下载</RingMetric>
              <RingMetric percentage={61.1} accent>
                11 / 18位普通投稿者重复投稿
              </RingMetric>
              <RingMetric percentage={44.5}>147 / 330位行为用户跨至少两个月活跃</RingMetric>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
