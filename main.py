from dify_plugin import Plugin, DifyPluginEnv

# 240s: slow AI answer engines (chatgpt/gemini/perplexity via Oxylabs) can
# legitimately take 60-110s; 120s left no headroom for parsing + summarizing.
plugin = Plugin(DifyPluginEnv(MAX_REQUEST_TIMEOUT=240))

if __name__ == '__main__':
    plugin.run()
