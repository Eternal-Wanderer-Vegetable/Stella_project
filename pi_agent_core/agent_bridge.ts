import { createAgentSession, ModelRuntime, SessionManager } from "@earendil-works/pi-coding-agent";
import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// 1. 读取人设 prompt
const promptPath = path.join(__dirname, "../prompt.txt");
const systemPrompt = fs.existsSync(promptPath)
  ? fs.readFileSync(promptPath, "utf-8")
  : "姓名：Stella\n性别：女\n你是一个兼具智能与温度的 AI 助手。";

async function main() {
  try {
    const inputBuffer = fs.readFileSync(0, "utf-8");
    if (!inputBuffer) return;

    const payload = JSON.parse(inputBuffer);
    const userPrompt = payload.prompt || "";

    // 2. 初始化 Model Runtime 并拉起 Agent Session
    const modelRuntime = await ModelRuntime.create();
    
    // 使用本地 LM Studio 配置（或 models.json / 默认配置）
    const model = modelRuntime.getModel("lm-studio", "stella-local");

    const { session } = await createAgentSession({
      sessionManager: SessionManager.inMemory(),
      modelRuntime: modelRuntime,
      model: model,
      systemPrompt: systemPrompt,
      tools: [] // 预留后续扩充的 Tools
    });

    // 3. 执行 prompt 并等待结果
    const result = await session.prompt(userPrompt);

    const output = {
      status: "success",
      reply: result.text
    };
    console.log(JSON.stringify(output));
  } catch (error: any) {
    const errorOutput = {
      status: "error",
      error: error.message || String(error)
    };
    console.log(JSON.stringify(errorOutput));
  }
}

main();