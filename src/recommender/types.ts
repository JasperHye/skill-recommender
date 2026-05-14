/**
 * Export the recommender module
 */
export { SkillRecommender, type Recommendation, type RecommenderOptions } from './index.js';
export { collectCandidates, type CandidateSkill, type CollectOptions } from './collector.js';
export { rankCandidates, type RankedCandidate, type UserProfile } from './ranker.js';
