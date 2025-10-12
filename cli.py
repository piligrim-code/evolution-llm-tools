import json, typer
from rich.console import Console
from .manager import code_react_loop
from .mcp.registry import ToolRegistry
from .config import settings

app = typer.Typer()
console = Console()

@app.command()
def run(question: str, model: str = typer.Option(None, help="Override Ollama model, e.g. 'llama3:latest'")):
    if model:
        settings.model = model  # динамически перекрываем модель
    res = code_react_loop(question)
    console.rule("[bold green]Final Answer")
    console.print(res["answer"])

@app.command("tools")
def list_tools():
    reg = ToolRegistry()
    tools = reg.list()
    console.print_json(data=tools)

@app.command("tool-run")
def tool_run(name: str, args: str = typer.Option("{}", help="JSON string for arguments")):
    reg = ToolRegistry()
    import json as _json
    res = reg.run(name, _json.loads(args))
    console.print(res)

if __name__ == "__main__":
    app()
