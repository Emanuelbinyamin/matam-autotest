#!/bin/bash
set -e

echo -e "\033[95m╔═══════════════════════════════════════════════╗\033[0m"
echo -e "\033[95m║  🐉 Installing Matam Auto-Test (234124)       ║\033[0m"
echo -e "\033[95m╚═══════════════════════════════════════════════╝\033[0m"

INSTALL_DIR="$HOME/matam-autotest"
REPO_URL="https://github.com/Emanuelbinyamin/matam-autotest.git"

# 1. Clone or update the repository
if [ -d "$INSTALL_DIR" ]; then
    echo -e "\033[96m→ Updating existing installation...\033[0m"
    cd "$INSTALL_DIR"
    git pull origin main --quiet
else
    echo -e "\033[96m→ Downloading autotest from GitHub...\033[0m"
    git clone "$REPO_URL" "$INSTALL_DIR" --quiet
fi

# 2. Setup the global bash alias
if ! grep -q "alias autotest=" ~/.bashrc; then
    echo -e "\033[96m→ Configuring terminal aliases...\033[0m"
    echo "alias autotest='python3 $INSTALL_DIR/autotest.py'" >> ~/.bashrc
else
    echo -e "\033[93m→ Alias already configured.\033[0m"
fi

echo -e "\n\033[92m✅ Installation Complete!\033[0m"
echo -e "\033[97mTo start using the monster immediately, run:\033[0m"
echo -e "  \033[93msource ~/.bashrc\033[0m"
echo -e "\033[97mThen type 'autotest main.cpp' in your homework folder!\033[0m\n"
