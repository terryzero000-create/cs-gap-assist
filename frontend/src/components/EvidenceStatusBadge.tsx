import type { EvidenceStatus } from '../types';

const labels: Record<EvidenceStatus, string> = {
  verified: '外部证据已验证',
  local_only: '仅使用本地真实证据',
  insufficient_evidence: '证据不足',
  provider_unavailable: '上游服务不可用',
  synthetic: '开发测试数据',
};

interface EvidenceStatusBadgeProps {
  status?: EvidenceStatus;
}

export function EvidenceStatusBadge({ status }: EvidenceStatusBadgeProps) {
  if (!status) {
    return null;
  }
  return <span className={`evidence-status evidence-status-${status}`}>{labels[status]}</span>;
}
