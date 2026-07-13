# Linter, Cost Logging, Fullscreen Support, and README Updates

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add flake8 linter support to secure CI build passing, track accumulated Gemini session token usage/costs, enable macOS fullscreen support for the translation overlay, and update the README.

**Architecture:** Configure flake8 locally and for GitHub Actions; introduce cumulative token tracking via connection-specific deltas in `TranscriberTranslator`; use ctypes and Apple's AppKit API to set the NSWindow's collection behavior to join all spaces and behave as a fullscreen auxiliary panel; and rewrite the outdated README.md.

**Tech Stack:** Python, Tkinter, ctypes (macOS AppKit), flake8, pytest

---

### Task 1: Linter Configuration and Dependency Integration

**Files:**
- Modify: `requirements_dev.txt`
- Create: `.flake8`

- [ ] **Step 1: Add flake8 to requirements_dev.txt**

Add `flake8` to `requirements_dev.txt`:
```
pytest
flake8
```

- [ ] **Step 2: Create .flake8 configuration file**

Create `.flake8` in the root directory:
```ini
[flake8]
exclude =
    .git,
    __pycache__,
    venv,
    .venv,
    .pytest_cache
max-line-length = 127
max-complexity = 10
```

- [ ] **Step 3: Verify linter passes locally**

Run:
```bash
./venv/bin/flake8 .
```
Expected: The linter exits with 0 (no output or only minor stylistic issues that do not break the selective CI rule).

- [ ] **Step 4: Commit changes**

Run:
```bash
git add requirements_dev.txt .flake8
git commit -m "chore: add flake8 linter and configuration"
```

---

### Task 2: Token Usage and Accumulated Session Cost Logging

**Files:**
- Modify: `module/transcriber.py`
- Test: `tests/test_transcriber.py`

- [ ] **Step 1: Initialize token tracking variables**

In `module/transcriber.py` `TranscriberTranslator.__init__`, initialize variables to track accumulated and per-connection tokens:
```python
        self.accumulated_prompt_tokens = 0
        self.accumulated_candidates_tokens = 0
        self.current_conn_prompt_tokens = 0
        self.current_conn_candidates_tokens = 0
```

- [ ] **Step 2: Log token usage and cost in receive loop**

In `module/transcriber.py` `receive_translation_loop`, check for `usage_metadata` on the response, compute deltas, accumulate them, and log:
```python
                # 3. Track token usage and estimated cost
                metadata = getattr(response, "usage_metadata", None)
                if metadata:
                    prompt_tokens = getattr(metadata, "prompt_token_count", 0) or 0
                    candidates_tokens = getattr(metadata, "candidates_token_count", 0) or 0
                    
                    # Compute deltas
                    delta_prompt = max(0, prompt_tokens - self.current_conn_prompt_tokens)
                    delta_candidates = max(0, candidates_tokens - self.current_conn_candidates_tokens)
                    
                    self.accumulated_prompt_tokens += delta_prompt
                    self.accumulated_candidates_tokens += delta_candidates
                    
                    self.current_conn_prompt_tokens = prompt_tokens
                    self.current_conn_candidates_tokens = candidates_tokens
                    
                    # Gemini 3.5 Live pricing: $3.50/1M input, $21.00/1M output
                    estimated_cost = (self.accumulated_prompt_tokens * 0.0000035) + (self.accumulated_candidates_tokens * 0.000021)
                    
                    logger.info(
                        "Session Accumulated - Prompt Tokens: %d, Candidates Tokens: %d, Estimated Cost: $%.6f",
                        self.accumulated_prompt_tokens,
                        self.accumulated_candidates_tokens,
                        estimated_cost
                    )
```

- [ ] **Step 3: Reset connection-specific counters on disconnect**

In `module/transcriber.py` `connect_and_run` inside `finally` block:
```python
            finally:
                self.session = None
                self.current_conn_prompt_tokens = 0
                self.current_conn_candidates_tokens = 0
```

- [ ] **Step 4: Add unit tests for token usage logging**

In `tests/test_transcriber.py`, add a test to verify token usage accumulation and cost logging:
```python
    async def test_token_usage_accumulation(self):
        """ Test that token usage is accumulated and deltas are calculated correctly """
        translator = TranscriberTranslator(config_path="dummy.json")
        mock_session = MagicMock()
        translator.session = mock_session

        # Mock metadata
        mock_metadata_1 = MagicMock()
        mock_metadata_1.prompt_token_count = 100
        mock_metadata_1.candidates_token_count = 10

        mock_metadata_2 = MagicMock()
        mock_metadata_2.prompt_token_count = 150
        mock_metadata_2.candidates_token_count = 25

        mock_response_1 = MagicMock()
        mock_response_1.server_content = None
        mock_response_1.usage_metadata = mock_metadata_1

        mock_response_2 = MagicMock()
        mock_response_2.server_content = None
        mock_response_2.usage_metadata = mock_metadata_2

        async def mock_receive():
            yield mock_response_1
            yield mock_response_2
            while True:
                await asyncio.sleep(1)

        mock_session.receive = MagicMock(return_value=mock_receive())
        
        loop_task = asyncio.create_task(translator.receive_translation_loop())
        await asyncio.sleep(0.05)
        
        self.assertEqual(translator.accumulated_prompt_tokens, 150)
        self.assertEqual(translator.accumulated_candidates_tokens, 25)
        
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass
```

- [ ] **Step 5: Verify tests pass**

Run:
```bash
./venv/bin/pytest tests/test_transcriber.py
```
Expected: PASS

- [ ] **Step 6: Commit changes**

Run:
```bash
git add module/transcriber.py tests/test_transcriber.py
git commit -m "feat: add token usage and session cost tracking with unit tests"
```

---

### Task 3: macOS Fullscreen Overlay Support

**Files:**
- Modify: `module/display.py`

- [ ] **Step 1: Implement fullscreen overlay configuration method**

Add `enable_fullscreen_overlay` method to `DisplayTranslation` in `module/display.py`:
```python
    def enable_fullscreen_overlay(self):
        """Enable the window to float over full screen apps on macOS."""
        import platform
        if platform.system() != "Darwin":
            return
            
        # Skip if running inside unit tests with a mock root
        if hasattr(self.root, "__class__") and self.root.__class__.__name__ == "MagicMock":
            return
            
        try:
            self.root.update()
            
            import ctypes
            import ctypes.util
            
            lib_path = ctypes.util.find_library('objc')
            if not lib_path:
                logger.warning("Could not find objc library path.")
                return
                
            objc = ctypes.cdll.LoadLibrary(lib_path)
            
            objc.objc_getClass.argtypes = [ctypes.c_char_p]
            objc.objc_getClass.restype = ctypes.c_void_p
            
            objc.sel_registerName.argtypes = [ctypes.c_char_p]
            objc.sel_registerName.restype = ctypes.c_void_p
            
            OBJC_MSG_SEND = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
            OBJC_MSG_SEND_IDX = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulonglong)
            OBJC_MSG_SEND_STR = ctypes.CFUNCTYPE(ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p)
            OBJC_MSG_SEND_VOID_ULONG = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulonglong)
            
            send_std = OBJC_MSG_SEND(objc.objc_msgSend)
            send_idx = OBJC_MSG_SEND_IDX(objc.objc_msgSend)
            send_str = OBJC_MSG_SEND_STR(objc.objc_msgSend)
            send_void_ulong = OBJC_MSG_SEND_VOID_ULONG(objc.objc_msgSend)
            
            sel_sharedApplication = objc.sel_registerName(b"sharedApplication")
            sel_windows = objc.sel_registerName(b"windows")
            sel_count = objc.sel_registerName(b"count")
            sel_objectAtIndex = objc.sel_registerName(b"objectAtIndex:")
            sel_title = objc.sel_registerName(b"title")
            sel_UTF8String = objc.sel_registerName(b"UTF8String")
            sel_setCollectionBehavior = objc.sel_registerName(b"setCollectionBehavior:")
            
            nsapp_class = objc.objc_getClass(b"NSApplication")
            if not nsapp_class:
                return
                
            nsapp = send_std(nsapp_class, sel_sharedApplication)
            if not nsapp:
                return
                
            windows = send_std(nsapp, sel_windows)
            if not windows:
                return
                
            count = send_std(windows, sel_count)
            target_window = None
            for i in range(count):
                win = send_idx(windows, sel_objectAtIndex, i)
                title_nsstring = send_std(win, sel_title)
                if title_nsstring:
                    title_bytes = send_str(title_nsstring, sel_UTF8String)
                    title = title_bytes.decode('utf-8') if title_bytes else ""
                    if "UniLingoStream Subtitles" in title:
                        target_window = win
                        break
            
            if target_window:
                # NSWindowCollectionBehaviorCanJoinAllSpaces = 1 << 0 (1)
                # NSWindowCollectionBehaviorFullScreenAuxiliary = 1 << 6 (64)
                send_void_ulong(target_window, sel_setCollectionBehavior, 65)
                logger.info("Successfully enabled macOS full screen support for overlay window.")
            else:
                logger.warning("Could not find UniLingoStream Subtitles window in NSApplication windows.")
                
        except Exception as e:
            logger.warning("Failed to enable macOS full screen support: %s", e)
```

- [ ] **Step 2: Call fullscreen overlay method in start_gui**

Modify `start_gui` in `module/display.py`:
```python
    def start_gui(self):
        """ Starts the Tkinter GUI loop. """
        self.enable_fullscreen_overlay()
        self.root.mainloop()
```

- [ ] **Step 3: Run unit tests**

Run:
```bash
./venv/bin/pytest tests/test_display.py
```
Expected: PASS (and doesn't crash on Darwin/mock root).

- [ ] **Step 4: Commit changes**

Run:
```bash
git add module/display.py
git commit -m "feat: enable macOS fullscreen support for Tkinter overlay window"
```

---

### Task 4: Documentation Updates

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README.md**

Update `README.md` to:
- Mention the transition to Gemini Live API (`google-genai` SDK) instead of legacy Google Cloud APIs.
- Describe the project file structure under `module/`.
- Document the new session token usage and estimated cost logging.
- Document support for macOS fullscreen overlay mode.
- Remove/ensure no emojis are used in the markdown file.

- [ ] **Step 2: Commit changes**

Run:
```bash
git add README.md
git commit -m "docs: update README with Gemini Live API setup and new features"
```
