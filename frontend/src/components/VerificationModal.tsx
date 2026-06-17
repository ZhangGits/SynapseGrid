/**
 * 验证结果弹窗 — 展示 Merkle 根比对结果
 *
 * Props:
 * - result: 验证结果
 * - onClose: 关闭回调
 */
interface VerifyResult {
  valid: boolean;
  session_id: string;
  merkle_root: string;
  event_count: number;
  content_signature: string;
  message: string;
}

interface Props {
  result: VerifyResult;
  onClose: () => void;
}

export function VerificationModal({ result, onClose }: Props) {
  return (
    <div className="verify-modal-overlay" onClick={onClose}>
      <div className="verify-modal" onClick={(e) => e.stopPropagation()}>
        <div className="verify-modal-header">
          <h3>🔒 完整性验证结果</h3>
          <button className="verify-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="verify-modal-body">
          <div className={`verify-status ${result.valid ? "valid" : "invalid"}`}>
            {result.valid ? "✅ 验证通过" : "❌ 验证失败"}
          </div>
          <div className="verify-details">
            <div className="verify-row">
              <span className="verify-label">会话 ID</span>
              <span className="verify-value mono">{result.session_id}</span>
            </div>
            <div className="verify-row">
              <span className="verify-label">Merkle 根</span>
              <span className="verify-value mono">{result.merkle_root}</span>
            </div>
            <div className="verify-row">
              <span className="verify-label">事件数</span>
              <span className="verify-value">{result.event_count}</span>
            </div>
            <div className="verify-row">
              <span className="verify-label">签名</span>
              <span className="verify-value mono">{result.content_signature.slice(0, 32)}...</span>
            </div>
            <div className="verify-row">
              <span className="verify-label">消息</span>
              <span className="verify-value">{result.message}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}