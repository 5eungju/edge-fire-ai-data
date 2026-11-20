
export const RISK_LEVELS = {
  1: {
    label: "정상",
    color: "green",
    description: "정상 관제 상태",
  },
  2: {
    label: "관심",
    color: "blue",
    description: "상태 변화 관찰 필요",
  },
  3: {
    label: "주의",
    color: "yellow",
    description: "주의 관제 필요",
  },
  4: {
    label: "경계",
    color: "orange",
    description: "위험 상황 집중 관제",
  },
  5: {
    label: "심각",
    color: "red",
    description: "긴급 대응 검토 필요",
  },
} as const;

export type RiskLevel = keyof typeof RISK_LEVELS;
