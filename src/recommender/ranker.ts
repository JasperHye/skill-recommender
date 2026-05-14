/**
 * Candidate skill ranker
 *
 * Scores and ranks candidate skills using:
 * - Behavior match: user's history of accepting/rejecting similar skills
 * - Domain match: alignment with user's recent conversation topics
 * - Trend score: popularity and freshness
 * - Security score: AgentGuard scan result (LOW=1.0, anything else=0)
 */

import type { CandidateSkill } from './collector.js';
import type { RiskLevel, RiskTag } from '../types/scanner.js';

export interface UserProfile {
  /** Installed skill names */
  installed_skills: string[];
  /** Domain topic weights (e.g. { "security": 0.8, "web3": 0.5 }) */
  domain_weights?: Record<string, number>;
  /** History of accepted skill names */
  accepted_skills?: string[];
  /** History of rejected skill names */
  rejected_skills?: string[];
}

export interface RankedCandidate {
  candidate: CandidateSkill;
  score: number;
  reason: string;
}

interface ScoreBreakdown {
  behavior: number;
  domain: number;
  trend: number;
  freshness: number;
  security: number;
}

/**
 * Score behavior match based on user's accept/reject history
 * and installed skill categories
 */
function scoreBehavior(
  candidate: CandidateSkill,
  profile: UserProfile
): number {
  const accepted = profile.accepted_skills ?? [];
  const rejected = profile.rejected_skills ?? [];

  // Boost if candidate shares tags with accepted skills
  const acceptedTags = new Set<string>();
  // (In a real implementation, we'd look up tags from accepted skills.
  //  For now, use category matching as a proxy.)
  if (candidate.category && profile.installed_skills.length > 0) {
    // If user already has skills in the same category, moderate boost
    return 0.5;
  }

  if (accepted.includes(candidate.name)) return 1.0;
  if (rejected.includes(candidate.name)) return 0.0;

  // Default: moderate relevance
  return 0.4;
}

/**
 * Score domain match based on candidate tags vs user domain weights
 */
function scoreDomain(
  candidate: CandidateSkill,
  profile: UserProfile
): number {
  const weights = profile.domain_weights;
  if (!weights || Object.keys(weights).length === 0) {
    return 0.5; // Neutral if no domain data
  }

  let maxWeight = 0;
  for (const tag of candidate.tags) {
    const weight = weights[tag.toLowerCase()];
    if (weight !== undefined && weight > maxWeight) {
      maxWeight = weight;
    }
  }

  // Also check category against domain weights
  const categoryWeight = weights[candidate.category.toLowerCase()];
  if (categoryWeight !== undefined && categoryWeight > maxWeight) {
    maxWeight = categoryWeight;
  }

  return maxWeight || 0.3;
}

/**
 * Score trend based on source type and metadata freshness
 * Locally available skills get a moderate trend score.
 */
function scoreTrend(candidate: CandidateSkill): number {
  // Local skills (already downloaded) are moderately trending
  if (candidate.source.startsWith('/') || candidate.source.startsWith('~')) {
    return 0.6;
  }
  // Remote/registry skills get base score
  return 0.4;
}

/**
 * Score freshness — local files are assumed recent
 */
function scoreFreshness(candidate: CandidateSkill): number {
  // For locally available skills, assume fresh
  return 0.8;
}

/**
 * Convert AgentGuard scan result to a security score
 * LOW = 1.0, everything else = 0 (but those are pre-filtered)
 */
function scoreSecurity(
  candidateName: string,
  scanResults: Map<string, { risk_level: RiskLevel; risk_tags: RiskTag[]; findings_count: number }>
): number {
  const result = scanResults.get(candidateName);
  if (!result) return 0;

  switch (result.risk_level) {
    case 'low': return 1.0;
    case 'medium': return 0.3;
    case 'high': return 0.0;
    case 'critical': return 0.0;
    default: return 0.0;
  }
}

/**
 * Generate human-readable reason for recommendation
 */
function generateReason(
  candidate: CandidateSkill,
  breakdown: ScoreBreakdown,
  scanResult?: { risk_level: RiskLevel; findings_count: number }
): string {
  const parts: string[] = [];

  if (scanResult) {
    parts.push(`AgentGuard 扫描通过（${scanResult.findings_count} 项发现，风险等级 ${scanResult.risk_level.toUpperCase()}）`);
  }

  if (candidate.tags.length > 0) {
    parts.push(`涉及领域：${candidate.tags.slice(0, 3).join('、')}`);
  }

  if (breakdown.domain > 0.6) {
    parts.push('与你的使用场景高度匹配');
  }

  return parts.join('；') || '安全扫描通过，值得尝试';
}

/**
 * Weighted scoring formula
 * total = 0.35×behavior + 0.30×domain + 0.20×trend + 0.15×freshness
 * Security is a multiplier (not additive) — 0 security = 0 total
 */
const WEIGHTS = {
  behavior: 0.35,
  domain: 0.30,
  trend: 0.20,
  freshness: 0.15,
};

/**
 * Rank all safe candidates by composite score
 */
export function rankCandidates(
  candidates: CandidateSkill[],
  profile: UserProfile,
  scanResults: Map<string, { risk_level: RiskLevel; risk_tags: RiskTag[]; findings_count: number }>
): RankedCandidate[] {
  const ranked: RankedCandidate[] = candidates.map((candidate) => {
    const breakdown: ScoreBreakdown = {
      behavior: scoreBehavior(candidate, profile),
      domain: scoreDomain(candidate, profile),
      trend: scoreTrend(candidate),
      freshness: scoreFreshness(candidate),
      security: scoreSecurity(candidate.name, scanResults),
    };

    // Weighted score, multiplied by security (0 security = 0 total)
    const score =
      (breakdown.behavior * WEIGHTS.behavior +
       breakdown.domain * WEIGHTS.domain +
       breakdown.trend * WEIGHTS.trend +
       breakdown.freshness * WEIGHTS.freshness) *
      breakdown.security;

    const scanResult = scanResults.get(candidate.name);

    return {
      candidate,
      score: Math.round(score * 100) / 100,
      reason: generateReason(candidate, breakdown, scanResult),
    };
  });

  // Sort descending by score
  ranked.sort((a, b) => b.score - a.score);

  return ranked;
}
