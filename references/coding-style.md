# Coding style

Decide this per language the task touches, in this order:

1. **The repo states rules.** Follow its linter and formatter configuration, `.editorconfig`, and any style notes in `CONTRIBUTING`, `CLAUDE.md` or similar. Run its formatter and linter if it has them.
2. **The repo has code in that language.** Follow what's there: naming, file layout, error handling, comment density, test style and common patterns. Look at the code closest to the change. Where the repo is inconsistent, follow the neighbouring code rather than tidying it up.
3. **The repo has nothing to go on.** That means a new repo, or the first code in that language. Use the Google style guide below. If the task sets up a new project, also add the guide's usual formatter or linter configuration where one exists, so that later tasks have rules to follow.

Google's guides never override an established repo. A repo using tabs stays on tabs, even if the guide says otherwise.

| Language | Google style guide |
|---|---|
| C++ | https://google.github.io/styleguide/cppguide.html |
| C# | https://google.github.io/styleguide/csharpguide.html |
| Go | https://google.github.io/styleguide/go/ |
| HTML and CSS | https://google.github.io/styleguide/htmlcssguide.html |
| Java | https://google.github.io/styleguide/javaguide.html |
| JavaScript | https://google.github.io/styleguide/jsguide.html |
| Objective-C | https://google.github.io/styleguide/objcguide.html |
| Python | https://google.github.io/styleguide/pyguide.html |
| R | https://google.github.io/styleguide/Rguide.html |
| Shell | https://google.github.io/styleguide/shellguide.html |
| Swift | https://google.github.io/swift/ |
| TypeScript | https://google.github.io/styleguide/tsguide.html |

For a language with no guide here, use its community standard formatter and conventions, and say so in the plan.

If a guide can't be fetched, apply what you know of it and say so in your report.
