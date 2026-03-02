# Git Worktree Guide

A worktree lets you work on a feature branch in a separate folder without touching your main working directory. Both folders share the same git history.

---

## When to Use a Worktree

- You want to develop a new feature without risking your stable `main` branch
- You want to test a change in isolation before merging
- You're working on multiple features at the same time

---

## Full Workflow

### 1. Create a worktree

Run this from the main repo (`AssistantMike/`):

```bash
git worktree add .worktrees/feature/my-feature -b feature/my-feature
```

This creates:
- A new branch called `feature/my-feature`
- A new folder at `.worktrees/feature/my-feature/` with a full copy of the code

### 2. Work in the worktree

```bash
cd .worktrees/feature/my-feature
```

Edit files, run commands, deploy — everything works the same as in the main folder.

```bash
# Deploy from the worktree
sam build && sam deploy

# Tail logs
sam logs --stack-name secretary-bot --name WebhookHandlerFunction --region ap-northeast-1 --tail
```

### 3. Commit your changes

```bash
git add -A
git commit -m "feature: describe what you built"
```

### 4. See what changed vs main

```bash
git diff main
```

### 5. Merge back to main

Switch back to the main repo folder and merge:

```bash
cd C:\Users\User\PycharmProjects\AssistantMike

git merge feature/my-feature
```

### 6. Clean up

```bash
# Remove the worktree folder
git worktree remove .worktrees/feature/my-feature

# Delete the branch (optional, do this after merging)
git branch -d feature/my-feature
```

---

## Quick Reference

| Task | Command |
|---|---|
| Create worktree | `git worktree add .worktrees/feature/NAME -b feature/NAME` |
| List all worktrees | `git worktree list` |
| See changes vs main | `git diff main` |
| Commit in worktree | `git add -A && git commit -m "message"` |
| Merge to main | `git merge feature/NAME` (from main folder) |
| Remove worktree | `git worktree remove .worktrees/feature/NAME` |
| Delete branch | `git branch -d feature/NAME` |

---

## Project Conventions

- Worktrees live in `.worktrees/` (gitignored — never committed)
- Branch name format: `feature/short-description`
- Always deploy and test from the worktree before merging to main

---

## How the Folders Relate

```
AssistantMike/                          ← main folder, branch: main
└── .worktrees/
    └── feature/my-feature/             ← worktree folder, branch: feature/my-feature
```

Both folders share the same `.git` — a commit in one is immediately visible to the other. Editing a file in the worktree does **not** affect `main` until you merge.

---

## Common Mistakes

| Mistake | Fix |
|---|---|
| Running `git diff master` | This repo uses `main`, not `master` — use `git diff main` |
| Editing files in the wrong folder | Run `git branch` to confirm which branch you're on |
| Deleting the worktree folder manually | Use `git worktree remove` instead, or run `git worktree prune` to clean up stale entries |
| Forgetting to merge before deleting | Run `git merge feature/NAME` from the main folder first |
