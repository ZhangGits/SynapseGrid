/**
 * 回退控件组件 — 显示可回退的分析要点列表
 *
 * 提供：
 * - 可回退的 finding ID 列表
 * - 回退按钮（带确认）
 * - 加载状态
 */

import { useState } from "react";

interface Props {
  rollbackable: string[];
  loading: boolean;
  onRollback: (findingId: string) => void;
}

export function RollbackControls({ rollbackable, loading, onRollback }: Props) {
  const [confirmId, setConfirmId] = useState<string | null>(null);

  if (rollbackable.length === 0) {
    return (
      <div className="rollback-controls">
        <h3>回退</h3>
        <p className="empty">无可回退的分析要点</p>
      </div>
    );
  }

  return (
    <div className="rollback-controls">
      <h3>回退</h3>
      <p className="rollback-hint">点击分析要点 ID 可回退该要点</p>
      <ul className="rollback-list">
        {rollbackable.map((fid) => (
          <li key={fid}>
            <span className="finding-id">{fid}</span>
            {confirmId === fid ? (
              <span className="confirm-actions">
                <button
                  className="confirm-yes"
                  onClick={() => {
                    onRollback(fid);
                    setConfirmId(null);
                  }}
                  disabled={loading}
                >
                  确认回退
                </button>
                <button
                  className="confirm-no"
                  onClick={() => setConfirmId(null)}
                >
                  取消
                </button>
              </span>
            ) : (
              <button
                className="rollback-btn"
                onClick={() => setConfirmId(fid)}
                disabled={loading}
              >
                回退
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
