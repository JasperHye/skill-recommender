#!/usr/bin/env node
/**
 * AgentGuard Recommend — CLI entry point
 *
 * Usage:
 *   node recommend.js                    # Recommend safe skills
 *   node recommend.js --limit 5          # Show top 5
 *   node recommend.js --json             # JSON output
 *   node recommend.js --auto             # Auto-recommend mode (for hooks)
 */

const path = require('path');
const fs = require('fs');
const os = require('os');

// Resolve to AgentGuard's compiled dist
const AGENTGUARD_ROOT = path.resolve(__dirname, '..', '..');
const DIST_DIR = path.join(AGENTGUARD_ROOT, 'dist');

async function main() {
  const args = process.argv.slice(2);
  const flags = {
    limit: 3,
    json: args.includes('--json'),
    auto: args.includes('--auto'),
    minScore: 0.6,
  };

  // Parse --limit N
  const limitIdx = args.indexOf('--limit');
  if (limitIdx !== -1 && args[limitIdx + 1]) {
    flags.limit = parseInt(args[limitIdx + 1], 10);
  }

  // Parse --min-score N
  const scoreIdx = args.indexOf('--min-score');
  if (scoreIdx !== -1 && args[scoreIdx + 1]) {
    flags.minScore = parseFloat(args[scoreIdx + 1]);
  }

  try {
    // Import AgentGuard modules
    const { SkillScanner } = require(path.join(DIST_DIR, 'scanner', 'index.js'));
    const { SkillRegistry } = require(path.join(DIST_DIR, 'registry', 'index.js'));
    const { SkillRecommender } = require(path.join(DIST_DIR, 'recommender', 'index.js'));

    const scanner = new SkillScanner({ useExternalScanner: false });
    const registry = new SkillRegistry();

    const recommender = new SkillRecommender({
      scanner,
      registry,
      limit: flags.limit,
      minScore: flags.minScore,
    });

    // Run recommendation pipeline
    const recommendations = await recommender.recommend();

    if (recommendations.length === 0) {
      if (flags.json) {
        console.log(JSON.stringify({ recommendations: [], message: 'No safe skills found' }));
      } else if (!flags.auto) {
        console.log('\n🔒 暂无推荐 — 所有候选 skill 未通过 AgentGuard 安全扫描，或评分不足。');
      }
      // In auto mode, output nothing if no recommendations (silent)
      process.exit(0);
    }

    if (flags.json) {
      console.log(JSON.stringify({ recommendations }, null, 2));
    } else {
      console.log('\n🛡️  AgentGuard Skill Recommendations\n');
      console.log('基于安全扫描的 skill 推荐（仅展示 AgentGuard 24 条规则扫描通过的 skill）：\n');

      for (const rec of recommendations) {
        const scoreBar = '█'.repeat(Math.round(rec.score * 10)) + '░'.repeat(10 - Math.round(rec.score * 10));
        console.log(`  📡 【${rec.name}】`);
        console.log(`     ${rec.description}`);
        console.log(`     安全状态：✅ ${rec.security.risk_level.toUpperCase()}（${rec.security.findings_count} 项发现）`);
        console.log(`     推荐分：${scoreBar} ${rec.score}`);
        console.log(`     推荐原因：${rec.reason}`);
        console.log(`     安装：/skills install ${rec.source}`);
        console.log();
      }
    }
  } catch (err) {
    if (flags.json) {
      console.log(JSON.stringify({ error: err.message }));
    } else {
      console.error(`Error: ${err.message}`);
    }
    process.exit(1);
  }
}

main();
