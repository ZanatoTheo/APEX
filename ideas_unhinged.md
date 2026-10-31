Here are ten ideas, ordered from "ambitious" to "definitely high". Each one grows out of something design.md already contains, so it reads as the system's own logic followed to its conclusion, not as decoration.

1. Replay the tape of life

Stephen Jay Gould asked whether evolution would turn out the same if you rewound and replayed it. Nobody can run that experiment on life on Earth; Apex can run it on agents. The ledger is append-only and every model output is logged (§7, §8), so you can fork from any block and replay with a different seed, hundreds of times.
- Science result: do independent replays keep finding the same axioms (convergent evolution means a real fitness peak), or does each history find its own solution (contingency)?
- Demo moment: 100 replays from one Genesis, drawn as a fan of phylogenies, with the axioms that keep re-evolving lighting up.
- Head start: the prototype already forks branches and records the seed, so this is mostly a "fork from block X" command.

2. Red Queen: tasks evolve too

The design's holdout is static and its custodian is a human (§13, Phase 2). Replace both with a second population: bug-injecting agents, whose fitness is breaking the fixers without breaking the hidden tests' validity. That makes a predator–prey arms race, with both populations in one Merkle ledger.
- The holdout custodian becomes an evolved adversary that the fixers can never see (§9.1 isolation, turned into a weapon).
- Demo moment: two fitness curves chasing each other, and the bug types that emerge (did the injectors invent a bug family nobody wrote?).

3. Gene knockout lab (causal attribution as genetics)

§10 requires every mutation to cite evidence, and the Causal Attribution Log is a stub. Take it all the way:
- Replay a frozen agent with one axiom or one graph node removed, the way biologists knock out a gene.
- Compute Shapley values: how much of the agent's score each "gene" carries.
- Then CRISPR: hand-write a targeted edit and confirm the predicted fitness gain on the holdout.
- Demo moment: a "genome browser" for an agent, where clicking an axiom shows its measured causal effect with a confidence interval.

4. Sex, speciation and mate choice

"Ledger Merging" is an open point (§18), and the design deliberately forbids it in the MVP. So build it:
- Crossover of two parents, with per-unit merge rules: graph from one, axioms from the other, AST splicing later.
- Species: the behavioral distance metric D(A₁, A₂) from §9 L3 defines species boundaries. Agents too far apart produce non-viable offspring, which the L0 gates kill.
- Mate choice: agents evolve a preference for partners' behavioral signatures. Sexual selection on prompts.
- Demo moment: watch one lineage split into two species that specialize in off-by-one vs type errors and then stop interbreeding.

5. A prediction market inside the swarm

Agents get a token wallet and bet on each other's hidden-holdout scores. Bets are hash-committed in the ledger before the holdout result is revealed (commit-reveal), so nobody can trade on hidden information, and the ledger proves it.
- Market prices become a fitness signal you can compare against UCB1, or use to replace it.
- L4 divergence (§9) becomes something agents profit from predicting: the swarm prices in overfitting.
- Demo moment: a ticker of agent "stocks", and a short-seller who called a lineage overfit before the holdout said so.

6. Apex evolves Apex

The mutation operator (Meta Muse Code) is the most important component, and it's a fixed prompt. Make it a population:
- Mutation prompts are selected by how much fitness their children gain.
- Then go one level up: UCB1's c, the L1 weights and the selection rule become mutation units too, changed only through §12's gate-patch governance. That gives a constitution with Merkle-proven amendments.
- High-level version: the swarm proposes changes to design.md itself, through the same C-ID change protocol this project used, and a human approves or rejects them. Your own planning workflow becomes the outermost evolutionary loop.

7. Pedigree papers for AI

§13 freezes Agent Specs. Ship each one with a verifiable evolutionary pedigree: the Merkle path from Genesis to the frozen spec, every mutation's cited evidence, and the held-out confidence interval. Anyone can verify it offline, like papers for a purebred dog or an SBOM for behaviour.
- Ambitious level: prove the holdout score in zero knowledge, showing an agent cleared 80% on hidden tests without revealing a single test. It isn't buildable in 10 days, which is the point for an ambition track. Show the ZK circuit design and a toy proof.

8. Fossils and Lazarus taxa

Every pruned agent is kept in the ledger (§10 Pruning). When the task distribution shifts (§12 rubric windows), resurrect extinct ancestors and see whether they beat their descendants: species that look extinct but come back, as in palaeontology. Add horizontal gene transfer: the Signal Watcher (§5) copies an axiom across lineages without descent. The phylogeny turns into a web, the ledger records it, and the ancestry stays verifiable.

9. Culture vs genes (the Baldwin effect)

Split inheritance into two channels:
- Genes: graph and axioms, changed by mutation.
- Culture: a shared tool and snippet library that agents write during their lifetime (code_ast, tool registry §14) and others can adopt. This is the Signal Watcher as cultural transmission.

Then measure the Baldwin effect: does in-lifetime learning speed up genetic evolution, and does what agents learn eventually get written into their axioms?

10. Draw an agent, watch it evolve

Use the SAM 3.1 pipeline the design reserves for Phase 3. A human sketches a workflow on a whiteboard, the vision model parses it into a Graph Config, and that becomes the seed of a new lineage that competes against machine-born ones. In reverse, render each agent as a creature whose body is its graph topology: verify loops as limbs, axioms as markings. The population view becomes a living ecosystem.

What I'd pitch

Combine 1 + 2 + 3: "A Galápagos for AI agents: we replayed evolution 100 times, armed the environment against it, and knocked out genes to prove what mattered." These three ideas share infrastructure the prototype already has (forkable ledger, logged outputs, holdout isolation, trace citations). Each produces a striking visual. And together they turn "agent optimizer" into "an experimental science of machine evolution", which is the kind of ambition jump an indie track rewards. Put 5 or 7 on a closing slide as "where this goes next".

Want me to turn this into a one-page pitch or a roadmap with what's demo-able in the remaining days?
