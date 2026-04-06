# My Travel Blog & Trip Reviews 🌍

这是我的个人旅行复盘与生活记录博客，基于 **Hugo** 框架构建，使用 **PaperMod** 主题。

## 🌐 访问链接

* **线上正式版**: [https://wanchang97.github.io/blog/](https://wanchang97.github.io/blog/)
    > *注：通过 GitHub Actions 自动部署。*
* **本地预览地址**: `http://localhost:1313/blog/`
    > *注：仅在本地运行 `hugo server` 时可用。*

## 🚀 常用本地命令

如果你想更新内容或预览，可以在终端使用以下命令：

1.  **本地预览**:
    ```bash
    hugo server -D
    ```
2.  **创建新文章**:
    ```bash
    hugo new posts/your-article-name.md
    ```
3.  **发布更新**:
    ```bash
    git add .
    git commit -m "Add new post"
    git push origin main
    ```

4.  **中文文章自动生成英文稿与德文稿（本地）**:
    ```bash
    export GEMINI_API_KEY="你的GeminiKey"
    python scripts/translate_posts.py --path content/posts/your-article-name.md
    ```
    > 会生成 `content/posts/your-article-name.en.md` 与 `your-article-name.de.md`，并写入 `source_hash` 方便增量更新。

5.  **批量翻译所有中文文章**:
    ```bash
    export GEMINI_API_KEY="你的GeminiKey"
    python scripts/translate_posts.py
    ```

## 📂 项目结构说明

* `content/posts/`: 存放旅行复盘的 Markdown 源文件。
* `static/`: 存放图片、PDF 等静态资源。
* `.github/workflows/hugo.yaml`: 负责自动把代码编译并发布到网页的脚本。
* `scripts/translate_posts.py`: 中文文章翻译为英文与德文的自动化脚本。
* `data/translation-glossary.yml`: 中→英术语映射（可按需扩充）。
* `data/translation-glossary-de.yml`: 中→德术语映射（可按需扩充）。

---
*Powered by [Hugo](https://gohugo.io/)*