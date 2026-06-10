# SkyPilot DPO Experiment Management Guide

## Setup Overview
- **Orchestrator:** `modules/accelerators/orchestrator/skypilot/`
- **Variants:** 9 combinations of LR (2e-6, 2e-7, 1e-6) × Beta (0.1, 0.2, 0.3)

---

## 🚀 Initial Launch Sequence

### 1. **Dry Run** (Always first!)
cd ~/modules/accelerators/orchestrator/skypilot
# Test without executing anything
bash schedules/base_schedule.sh --dry-run variants/lr_*.yml

What you'll see:
- Resource allocation (GPUs, CPUs, memory)
- List of all variants found
- Commands that WOULD be executed
- Generated config paths
- Cluster names that WILL be created

### 2. Full Execution (Sequential - one at a time)
# Basic execution with default config.yml
bash schedules/base_schedule.sh variants/lr_*.yml

# With logging to file (recommended)
bash schedules/base_schedule.sh variants/lr_*.yml 2>&1 | tee training_$(date +%Y%m%d_%H%M%S).log

# With custom cluster prefix for easier identification
bash schedules/base_schedule.sh --cluster-prefix dpo-run1 variants/lr_*.yml 2>&1 | tee dpo_run1.log

### 3. If something goes wrong mid-run
# Stop current execution (Ctrl+C)
# Then resume with remaining variants only
bash schedules/base_schedule.sh variants/lr_2e-07_beta_01.yml variants/lr_2e-07_beta_02.yml variants/lr_2e-07_beta_03.yml variants/lr_e-06_beta_01.yml variants/lr_e-06_beta_02.yml variants/lr_e-06_beta_03.yml

---

## 📊 Monitoring Commands

### Check cluster status
# List all active clusters
sky status

# More detailed view
sky status -a

# Show only cluster names
sky status --names

# Watch in real-time (updates every 5 seconds)
watch -n 5 sky status

### View logs
# Follow logs of specific cluster (real-time)
sky logs dpo-run1-0 --follow

# Get last N lines
sky logs dpo-run1-0 --tail 100

# Get logs from specific time
sky logs dpo-run1-0 --start-time "2025-01-15 10:00:00"

# Stream logs without following (just show and exit)
sky logs dpo-run1-0

### Check cluster details
# Get cluster information (IP, resources, status)
sky status -d dpo-run1-0

# Show cluster configuration
sky status --show-config dpo-run1-0

### SSH into cluster
# Interactive SSH session
sky ssh dpo-run1-0

# Run command without entering
sky ssh dpo-run1-0 --command "nvidia-smi"

# Check GPU utilization
sky ssh dpo-run1-0 --command "nvidia-smi --query-gpu=utilization.gpu --format=csv"

---

## 🛑 Stopping and Cleanup

### Stop specific clusters
# Stop one cluster
sky stop dpo-run1-0

# Stop multiple clusters
sky stop dpo-run1-0 dpo-run1-1 dpo-run1-2

# Stop all clusters with prefix
sky stop dpo-run1-*

### Terminate/Delete clusters (releases resources)
# Terminate one cluster
sky down dpo-run1-0

# Terminate all experiment clusters
sky down dpo-run1-*

# Terminate ALL clusters (careful!)
sky down --all

### Restart stopped cluster
# Restart a stopped cluster
sky start dpo-run1-0
# Cluster will resume from where it stopped

---

## 📝 Logging Strategies

### Option 1: Simple per-run log file
# One log file for entire experiment
bash schedules/base_schedule.sh variants/lr_*.yml 2>&1 | tee full_experiment.log
# View while running: tail -f full_experiment.log

### Option 2: Separate logs per variant
Create a wrapper script run_with_variant_logs.sh:
#!/bin/bash
for variant in variants/lr_*.yml; do
    variant_name=$(basename "$variant" .yml)
    echo "Running $variant_name..."
    bash schedules/base_schedule.sh "$variant" 2>&1 | tee "logs/${variant_name}.log"
done

### Option 3: SkyPilot's built-in logging
# Logs are stored in ~/.sky/logs/ on your local machine
ls ~/.sky/logs/

# Check SkyPilot's internal logs for debugging
cat ~/.sky/logs/sky-2025-01-15-10-30-45.log

### Option 4: Remote logs on cluster
# After SSH into cluster, check training logs
sky ssh dpo-run1-0
cat /path/to/training/output.log

# Or copy logs locally
sky rsync -a dpo-run1-0:/path/to/logs/ ./local_logs/

---

## 🔍 Debugging Common Issues

### Problem: Cluster stuck in provisioning
# Check detailed status
sky status -d dpo-run1-0

# Check cloud provider events
sky logs dpo-run1-0 --controller

# Try to cancel and recreate
sky down dpo-run1-0
# Then re-run the variant

### Problem: Can't see progress bars
Fix in your train.py:
import sys
sys.stdout.reconfigure(line_buffering=True)  # Python 3.7+
# Or use these flags when launching (in task_template.yaml)
# python -u train.py ${CONFIG_PATH}

### Problem: Out of disk space
# Check disk usage on cluster
sky ssh dpo-run1-0 --command "df -h"

# Clean up cached data
sky ssh dpo-run1-0 --command "rm -rf ~/.cache/huggingface/datasets/*"

### Problem: Need to see real-time GPU metrics
# Watch GPU usage across all experiment clusters
watch -n 2 'sky status --all | grep dpo-run1 && sky ssh dpo-run1-0 --command "nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv"'

---

## 📋 Quick Reference Card

| Action | Command |
| :--- | :--- |
| Dry run | bash schedules/base_schedule.sh --dry-run variants/lr_*.yml |
| Start sequential | bash schedules/base_schedule.sh variants/lr_*.yml |
| Start with logging | bash schedules/base_schedule.sh variants/lr_*.yml 2>&1 \| tee run.log |
| Check clusters | sky status |
| Follow logs | sky logs CLUSTER_NAME --follow |
| Stop cluster | sky stop CLUSTER_NAME |
| Terminate cluster | sky down CLUSTER_NAME |
| SSH into cluster | sky ssh CLUSTER_NAME |
| List all clusters | sky status -a |
| Kill all experiment | sky down dpo-run1-* |

---

## 🎯 Your Specific Workflow Example
# 1. Navigate to orchestrator
cd /home/velvet/DPO-unsloth-setup/modules/accelerators/orchestrator/skypilot

# 2. Create logs directory
mkdir -p logs

# 3. Dry run to verify everything
bash schedules/base_schedule.sh --dry-run --cluster-prefix dpo-test variants/lr_*.yml

# 4. Launch for real with logging
bash schedules/base_schedule.sh --cluster-prefix dpo-exp1 variants/lr_*.yml 2>&1 | tee logs/dpo_exp1_$(date +%Y%m%d_%H%M%S).log

# 5. In another terminal, monitor progress
watch -n 5 sky status

# 6. When needed, check logs of current variant
sky logs dpo-exp1-0 --follow

# 7. After all variants complete, cleanup
sky down dpo-exp1-*

# 8. Verify cleanup
sky status

---

## 💡 Pro Tips
- Always use --dry-run before real execution - saves from costly mistakes.
- Set meaningful cluster prefixes to easily identify experiments:
--cluster-prefix "2025-01-15-lr-beta-sweep"

- Save your logs! They're invaluable for debugging:
bash schedules/base_schedule.sh variants/lr_*.yml 2>&1 | tee logs/$(date +%Y%m%d_%H%M%S)_experiment.log

- Monitor disk space on clusters during long runs:
sky ssh CLUSTER_NAME --command "df -h / && du -sh ~/.cache"

- Use tmux or screen for long-running experiments to survive disconnections:
tmux new -s dpo_experiment
# Run your command inside tmux
# Detach with Ctrl+B, D
# Reattach with: tmux attach -t dpo_experiment

- Check costs after experiments:
# SkyPilot doesn't track costs natively, but you can check cloud provider console
# Or estimate: A100-80GB ~ $3-4/hour × runtime hours

---

## 🆘 Emergency Commands
# Kill ALL SkyPilot clusters (force)
sky down --all

# Stop all experiment clusters immediately
sky status --names | grep dpo-exp1 | xargs -I {} sky down {}

# If SkyPilot is stuck, restart it
sky stop --all
sky start --all

# Complete reset (last resort)
rm -rf ~/.sky/generated/

---

## 📚 Useful SkyPilot Commands Reference
# Autocomplete is your friend! Press Tab after typing 'sky'
sky [TAB]  # Shows all available commands

# Get help for any command
sky status --help
sky launch --help

# Show version and configuration
sky version
sky check  # Verify cloud access and setup

Remember: Your script handles everything automatically - you just need to monitor and cleanup!