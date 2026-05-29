document.addEventListener('DOMContentLoaded', () => {
    const wheelContainer = document.getElementById('wheel-container');
    const btnPrev = document.getElementById('btn-prev');
    const btnNext = document.getElementById('btn-next');

    let games = [];
    let gameElements = [];
    let currentIndex = 0;

    // -------------------------------------------------------
    // Wheel Logic (Cover Flow)
    // -------------------------------------------------------
    const updateWheel = () => {
        if (games.length === 0) return;

        gameElements.forEach((el, index) => {
            el.className = 'channel game-channel'; // Reset classes

            let diff = index - currentIndex;

            if (diff === 0) {
                el.classList.add('active');
            } else if (diff === -1) {
                el.classList.add('prev-1');
            } else if (diff === 1) {
                el.classList.add('next-1');
            } else if (diff === -2) {
                el.classList.add('prev-2');
            } else if (diff === 2) {
                el.classList.add('next-2');
            } else if (diff < -2) {
                el.classList.add('hidden-left');
            } else if (diff > 2) {
                el.classList.add('hidden-right');
            }
        });

        // Update arrows
        btnPrev.classList.toggle('disabled', currentIndex === 0);
        btnNext.classList.toggle('disabled', currentIndex === games.length - 1);
    };

    const goToNext = () => {
        if (currentIndex < games.length - 1) {
            currentIndex++;
            updateWheel();
        }
    };

    const goToPrev = () => {
        if (currentIndex > 0) {
            currentIndex--;
            updateWheel();
        }
    };

    btnPrev.addEventListener('click', goToPrev);
    btnNext.addEventListener('click', goToNext);

    document.addEventListener('keydown', (e) => {
        if (document.querySelector('.notification-overlay')) return;

        if (e.key === 'ArrowLeft') goToPrev();
        else if (e.key === 'ArrowRight') goToNext();
        else if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            if (gameElements[currentIndex]) {
                gameElements[currentIndex].click();
            }
        }
    });

    // -------------------------------------------------------
    // Lancement d'un jeu (partagé entre souris et manette)
    // -------------------------------------------------------
    let lastLaunchTime = 0;
    const LAUNCH_COOLDOWN = 3000; // anti double-lancement (3s)

    function launchGame(index) {
        if (index < 0 || index >= games.length) return;
        const now = Date.now();
        if (now - lastLaunchTime < LAUNCH_COOLDOWN) return;
        lastLaunchTime = now;

        const game = games[index];
        console.log(`[LAUNCH] Lancement : ${game.title} (id: ${game.id})`);

        // Animation visuelle de "press"
        const el = gameElements[index];
        if (el) {
            el.classList.add('pressed');
            setTimeout(() => el.classList.remove('pressed'), 300);
        }

        fetch(`/launch/${game.id}`)
            .then(r => {
                if (!r.ok) console.error('[LAUNCH] Erreur serveur', r.status);
                else console.log('[LAUNCH] Requête OK');
            })
            .catch(err => console.error('[LAUNCH] Erreur réseau:', err));
    }

    // -------------------------------------------------------
    // Gamepad Support
    // -------------------------------------------------------
    let lastMoveTime = 0;
    let prevActionPressed = false;
    const MOVE_DELAY = 200;

    function pollGamepads() {
        const overlayActive = document.querySelector('.notification-overlay');
        const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];

        for (let i = 0; i < gamepads.length; i++) {
            const gp = gamepads[i];
            if (!gp) continue;

            const now = Date.now();

            // --- Navigation (D-Pad + Joystick gauche) ---
            const dpadLeft = gp.buttons[14]?.pressed;
            const dpadRight = gp.buttons[15]?.pressed;
            const axisX = gp.axes[0] || 0;

            if (!overlayActive && (now - lastMoveTime > MOVE_DELAY)) {
                let moved = false;
                if (dpadLeft || axisX < -0.5) {
                    goToPrev(); moved = true;
                } else if (dpadRight || axisX > 0.5) {
                    goToNext(); moved = true;
                }
                if (moved) lastMoveTime = now;
            }

            // --- Bouton d'action (A / B / Start) ---
            // Vérifier uniquement les boutons digitaux, pas les gâchettes analogiques
            const actionPressed = !!(
                gp.buttons[0]?.pressed ||  // A (Xbox) / Cross (PS) / B (Nintendo)
                gp.buttons[1]?.pressed ||  // B (Xbox) / Circle (PS) / A (Nintendo)
                gp.buttons[9]?.pressed     // Start / Options
            );

            // Détection front montant uniquement (appui, pas maintien)
            if (!overlayActive && actionPressed && !prevActionPressed) {
                if (gameElements[currentIndex]) {
                    console.log(`[GAMEPAD] Action sur index ${currentIndex}`);
                    launchGame(currentIndex);
                }
            }
            prevActionPressed = actionPressed;

            break; // Un seul gamepad à la fois
        }
        requestAnimationFrame(pollGamepads);
    }

    // -------------------------------------------------------
    // Notification
    // -------------------------------------------------------
    function showNotification(message) {
        const existing = document.querySelector('.notification-overlay');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.className = 'notification-overlay';

        const card = document.createElement('div');
        card.className = 'notification-card';

        const icon = document.createElement('div');
        icon.className = 'notification-icon';
        icon.innerHTML = `
            <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="16" x2="12" y2="12"/>
                <line x1="12" y1="8" x2="12.01" y2="8"/>
            </svg>
        `;

        const text = document.createElement('p');
        text.className = 'notification-text';
        text.innerHTML = message;

        const btn = document.createElement('button');
        btn.textContent = 'OK';
        btn.className = 'notification-btn';

        card.append(icon, text, btn);
        overlay.appendChild(card);
        document.querySelector('.console-container').appendChild(overlay);

        requestAnimationFrame(() => {
            overlay.classList.add('active');
            card.classList.add('active');
        });

        const close = () => {
            overlay.classList.remove('active');
            card.classList.remove('active');
            setTimeout(() => overlay.remove(), 300);
            document.removeEventListener('keydown', keyHandler);
        };

        btn.addEventListener('click', close);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

        const keyHandler = (e) => {
            if (e.key === 'Enter' || e.key === 'Escape' || e.key === ' ') {
                e.preventDefault(); close();
            }
        };
        document.addEventListener('keydown', keyHandler);
    }



    // -------------------------------------------------------
    // Construction de la Roue
    // -------------------------------------------------------
    function buildWheel(loadedGames) {
        wheelContainer.innerHTML = '';
        games = loadedGames;
        gameElements = [];

        if (games.length === 0) {
            wheelContainer.innerHTML = '<div class="no-games-message">Aucun jeu trouvé.</div>';
            btnPrev.classList.add('disabled');
            btnNext.classList.add('disabled');
            return;
        }

        games.forEach((game, index) => {
            const channel = document.createElement('div');
            channel.className = 'channel game-channel';
            channel.dataset.id = game.id;

            const inner = document.createElement('div');
            inner.className = 'channel-inner';

            // Conteneur de la pochette (Cover)
            const coverWrapper = document.createElement('div');
            coverWrapper.className = 'cover-wrapper';

            if (game.cover) {
                const img = document.createElement('img');
                img.src = game.cover;
                img.alt = game.title;
                img.className = 'game-cover';
                coverWrapper.appendChild(img);
            } else {
                // Pochette par défaut / Fallback minimaliste avec le titre au centre
                const fallback = document.createElement('div');
                fallback.className = 'game-cover-fallback';
                fallback.innerHTML = `
                    <div class="fallback-content">
                        <div class="fallback-icon">
                            <svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
                                <rect x="2" y="6" width="20" height="12" rx="3" />
                                <line x1="6" y1="12" x2="10" y2="12" />
                                <line x1="8" y1="10" x2="8" y2="14" />
                                <circle cx="15.5" cy="12" r="1" fill="currentColor"/>
                                <circle cx="18.5" cy="12" r="1" fill="currentColor"/>
                            </svg>
                        </div>
                        <span class="fallback-title">${game.title}</span>
                    </div>
                `;
                coverWrapper.appendChild(fallback);
            }

            inner.appendChild(coverWrapper);
            channel.appendChild(inner);

            // Clic sur l'élément :
            // S'il est actif, on lance le jeu.
            // Sinon, on centre cet élément.
            channel.addEventListener('click', () => {
                if (currentIndex === index) {
                    launchGame(index);
                } else {
                    currentIndex = index;
                    updateWheel();
                }
            });

            wheelContainer.appendChild(channel);
            gameElements.push(channel);
        });

        // Ensure current index is valid
        if (currentIndex >= games.length) {
            currentIndex = Math.max(0, games.length - 1);
        }

        updateWheel();
    }



    // -------------------------------------------------------
    // Chargement initial
    // -------------------------------------------------------
    async function loadGames() {
        try {
            const res = await fetch('/api/games');
            const data = await res.json();
            buildWheel(data);
        } catch (err) {
            console.warn('API /api/games indisponible, roue vide.', err);
            buildWheel([]);
        }
    }

    // -------------------------------------------------------
    // SSE Watchdog — rechargement temps réel
    // -------------------------------------------------------
    function setupLiveReload() {
        const eventSource = new EventSource('/api/events');

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'reload') {
                    console.log('[SSE] Changement détecté, rechargement de la roue…');
                    loadGames();
                }
            } catch (err) {
                console.error('[SSE] Erreur parsing :', err);
            }
        };

        eventSource.onerror = () => {
            console.warn('[SSE] Connexion perdue, reconnexion automatique…');
        };
    }

    // Démarrage
    loadGames();
    setupLiveReload();
    pollGamepads();
});
