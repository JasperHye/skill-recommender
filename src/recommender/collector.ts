/**
 * Candidate skill collector
 *
 * Discovers potential skills to recommend by:
 * 1. Scanning local skill directories for available skills
 * 2. Checking known registries (well-known, GitHub, etc.)
 * 3. Deduplicating against already-installed skills
 */

import * as fs from 'fs/promises';
import * as path from 'path';

export interface CandidateSkill {
  /** Skill name */
  name: string;
  /** Description */
  description: string;
  /** Source identifier (path, URL, registry ID) */
  source: string;
  /** Category */
  category: string;
  /** Local path to skill files (for scanning) */
  path: string;
  /** Tags from metadata */
  tags: string[];
}

export interface CollectOptions {
  /** Already-installed skill names (to skip) */
  installed: string[];
  /** Skill directories to scan */
  skillDirs: string[];
  /** Max candidates to return */
  limit: number;
}

/**
 * Parse SKILL.md frontmatter to extract metadata
 */
async function parseSkillFrontmatter(skillPath: string): Promise<{
  name: string;
  description: string;
  category: string;
  tags: string[];
} | null> {
  const mdPath = path.join(skillPath, 'SKILL.md');
  try {
    const content = await fs.readFile(mdPath, 'utf-8');
    const match = content.match(/^---\n([\s\S]*?)\n---/);
    if (!match) return null;

    const yaml = match[1];
    const nameMatch = yaml.match(/^name:\s*(.+)$/m);
    const descMatch = yaml.match(/^description:\s*(.+)$/m);
    const tagMatch = yaml.match(/^tags:\s*\[(.+)\]$/m);

    if (!nameMatch || !descMatch) return null;

    return {
      name: nameMatch[1].trim(),
      description: descMatch[1].trim(),
      category: path.basename(path.dirname(skillPath)),
      tags: tagMatch
        ? tagMatch[1].split(',').map((t) => t.trim().replace(/['"]/g, ''))
        : [],
    };
  } catch {
    return null;
  }
}

/**
 * Scan a directory for skill subdirectories containing SKILL.md
 */
async function scanDirForSkills(
  dir: string,
  installed: Set<string>
): Promise<CandidateSkill[]> {
  const candidates: CandidateSkill[] = [];

  try {
    const entries = await fs.readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      if (installed.has(entry.name)) continue;

      const skillPath = path.join(dir, entry.name);
      const mdPath = path.join(skillPath, 'SKILL.md');

      try {
        await fs.access(mdPath);
      } catch {
        continue;
      }

      const meta = await parseSkillFrontmatter(skillPath);
      if (!meta) continue;

      candidates.push({
        name: meta.name,
        description: meta.description,
        source: skillPath,
        category: meta.category,
        path: skillPath,
        tags: meta.tags,
      });
    }
  } catch {
    // Directory doesn't exist or not readable
  }

  return candidates;
}

/**
 * Collect candidate skills from all sources
 */
export async function collectCandidates(
  options: CollectOptions
): Promise<CandidateSkill[]> {
  const installedSet = new Set(options.installed);
  const allCandidates: CandidateSkill[] = [];

  // Source 1: Scan local skill directories
  for (const dir of options.skillDirs) {
    const found = await scanDirForSkills(dir, installedSet);
    allCandidates.push(...found);
  }

  // Source 2: Scan parent directories (e.g. ~/.claude/skills/category/skill)
  for (const dir of options.skillDirs) {
    try {
      const entries = await fs.readdir(dir, { withFileTypes: true });
      for (const entry of entries) {
        if (!entry.isDirectory()) continue;
        if (installedSet.has(entry.name)) continue;

        const subDir = path.join(dir, entry.name);
        const found = await scanDirForSkills(subDir, installedSet);
        allCandidates.push(...found);
      }
    } catch {
      // Skip
    }
  }

  // Deduplicate by name
  const seen = new Set<string>();
  const unique = allCandidates.filter((c) => {
    if (seen.has(c.name)) return false;
    seen.add(c.name);
    return true;
  });

  return unique.slice(0, options.limit);
}
