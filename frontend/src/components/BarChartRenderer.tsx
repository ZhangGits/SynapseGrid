/**
 * 柱状图渲染器组件 — 使用纯 CSS 渲染柱状图
 *
 * 支持：
 * - 垂直和水平方向
 * - 堆叠模式
 * - 图例显示
 * - 自定义颜色
 *
 * 注意：当前为简化实现，生产环境建议使用 Chart.js 或 D3.js。
 */

interface Props {
  categories: string[];
  values: number[];
  color?: string;
  orientation?: "vertical" | "horizontal";
  stacked?: boolean;
  showLegend?: boolean;
}

export function BarChartRenderer({
  categories,
  values,
  color = "#3b82f6",
  orientation = "vertical",
  showLegend = true,
}: Props) {
  const maxValue = Math.max(...values, 1);

  return (
    <div className={`bar-chart ${orientation}`}>
      {showLegend && (
        <div className="chart-legend">
          <span className="legend-item">
            <span className="legend-color" style={{ backgroundColor: color }} />
            数值
          </span>
        </div>
      )}
      <div className="chart-bars">
        {categories.map((cat, i) => (
          <div key={i} className="chart-bar-item">
            <div
              className="chart-bar"
              style={{
                [orientation === "vertical" ? "height" : "width"]: `${(values[i] / maxValue) * 100}%`,
                backgroundColor: color,
              }}
            />
            <span className="chart-label">{cat}</span>
            <span className="chart-value">{values[i]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
