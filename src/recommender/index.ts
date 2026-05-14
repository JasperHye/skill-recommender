/**
 * GoPlus AgentGuard - Skill Recommender
 *
 * Discovers, scans, ranks, and recommends safe skills.
 * Integrates AgentGuard's scanner (24 rules) as the security gate:
 * only skills with risk_level "low" pass through.
 *
 * Usage:
 *   const { scanner, registry } = createAgentGuard();
 *   const recommender = new SkillRecommender({ scanner, registry });
 *   const results = await recommender.recommend();
 */

import * as path from 'path';
import * as os from 'os';
import { SkillScanner } from '../scanner/index.js';
import { SkillRegistry } from '../registry/index.js';
import { collectCandidates, type CandidateSkill } from './collector.js';
import { rankCandidates, type RankedCandidate, type UserProfile } from './ranker.js';
import type { RiskLevel, RiskTag } from '../types/scanner.js';

/**
 * A recommended skill with security attestation
 */
export interface Recommendation {
  /** Skill name */
  name: string;
  /** Description */
  description: string;
  /** Source path or identifier */
  source: string;
  /** Category (if known) */
  category: string;
  /** AgentGuard scan result */
  security: {
    risk_level: RiskLevel;
    risk_tags: RiskTag[];
    findings_count: number;
  };
  /** Composite score (0-1) */
  score: number;
  /** Why this skill was recommended */
  reason: string;
}

export interface RecommenderOptions {
  /** AgentGuard scanner instance */
  scanner: SkillScanner;
  /** AgentGuard registry instance */
  registry?: SkillRegistry;
  /** Max recommendations to return */
  limit?: number;
  /** Minimum score threshold (0-1) */
  minScore?: number;
  /** Paths to scan for installed skills */
  skillDirs?: string[];
}

const DEFAULT_SKILL_DIRS = [
  path.join(os.homedir(), '.claude', 'skills'),
  path.join(os.homedir(), '.openclaw', 'skills'),
  path.join(os.homedir(), '.hermes', 'skills'),
];

export class SkillRecommender {
  private scanner: SkillScanner;
  private registry?: SkillRegistry;
  private limit: number;
  private minScore: number;
  private skillDirs: string[];

  constructor(options: RecommenderOptions) {
    this.scanner = options.scanner;
    this.registry = options.registry;
    this.limit = options.limit ?? 3;
    this.minScore = options.minScore ?? 0.6;
    this.skillDirs = options.skillDirs ?? DEFAULT_SKILL_DIRS;
  }

  /**
   * Get list of currently installed skill names
   */
  async getInstalledSkills(): Promise<string[]> {
    const fs = await import('fs/promises');
    const installed: string[] = [];

    for (const dir of this.skillDirs) {
      try {
        const entries = await fs.readdir(dir, { withFileTypes: true });
        for (const entry of entries) {
          if (entry.isDirectory()) {
            installed.push(entry.name);
          }
        }
      } catch {
        // Directory doesn't exist, skip
      }
    }

    return [...new Set(installed)];
  }

  /**
   * Scan a candidate skill with AgentGuard's 24-rule engine
   */
  async scanCandidate(candidate: CandidateSkill): Promise<{
    risk_level: RiskLevel;
    risk_tags: RiskTag[];
    findings_count: number;
  }> {
    try {
      const result = await this.scanner.scan({
        skill: {
          id: candidate.name,
          source: candidate.source,
          version_ref: 'latest',
          artifact_hash: '',
        },
        payload: {
          type: 'dir',
          ref: candidate.path,
        },
      });

      return {
        risk_level: result.risk_level,
        risk_tags: result.risk_tags,
        findings_count: result.evidence.length,
      };
    } catch {
      // Scan failed — treat as untrusted
      return {
        risk_level: 'critical' as RiskLevel,
        risk_tags: ['REMOTE_LOADER' as RiskTag],
        findings_count: -1,
      };
    }
  }

  /**
   * Run the full recommendation pipeline:
   * collect → scan → filter → rank → return top N
   */
  async recommend(userProfile?: Partial<UserProfile>): Promise<Recommendation[]> {
    // Step 1: Build user profile from installed skills
    const installed = await this.getInstalledSkills();
    const profile: UserProfile = {
      installed_skills: installed,
      ...userProfile,
    };

    // Step 2: Collect candidates
    const candidates = await collectCandidates({
      installed,
      skillDirs: this.skillDirs,
      limit: 50, // Collect more than we need, filter later
    });

    if (candidates.length === 0) {
      return [];
    }

    // Step 3: Scan each candidate with AgentGuard
    const scanResults = new Map<string, {
      risk_level: RiskLevel;
      risk_tags: RiskTag[];
      findings_count: number;
    }>();

    const scanPromises = candidates.map(async (candidate) => {
      const result = await this.scanCandidate(candidate);
      scanResults.set(candidate.name, result);
      return { candidate, security: result };
    });

    const scanned = await Promise.all(scanPromises);

    // Step 4: Filter — only LOW risk passes
    const safeCandidates = scanned.filter(
      (s) => s.security.risk_level === 'low'
    );

    if (safeCandidates.length === 0) {
      return [];
    }

    // Step 5: Rank
    const ranked = rankCandidates(
      safeCandidates.map((s) => s.candidate),
      profile,
      scanResults
    );

    // Step 6: Filter by min score and take top N
    const recommendations: Recommendation[] = ranked
      .filter((r) => r.score >= this.minScore)
      .slice(0, this.limit)
      .map((r) => {
        const security = scanResults.get(r.candidate.name)!;
        return {
          name: r.candidate.name,
          description: r.candidate.description,
          source: r.candidate.source,
          category: r.candidate.category,
          security: {
            risk_level: security.risk_level,
            risk_tags: security.risk_tags,
            findings_count: security.findings_count,
          },
          score: r.score,
          reason: r.reason,
        };
      });

    return recommendations;
  }
}
