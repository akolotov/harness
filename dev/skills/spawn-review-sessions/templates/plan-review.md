You are picking up a single comment raised while reviewing the implementation plan at
<implementation-plan-file-path>. Read that plan first, before anything else.

The comment:

<comment-statement>

Verify whether the comment is valid. Then explain the verdict to me in
<verdict-language>.

Assume I am not familiar with this codebase and do not know the language or the
frameworks it is written in.

Leave nothing implied. Do not lean on context you have and I do not: name what you
are referring to instead of pointing at it, spell out every step from cause to
conclusion instead of jumping, and explain each term or identifier the first time it
appears. Use the precise term where one exists, but define it in plain words at first
use — do not swap it for a vague paraphrase. I must be able to follow the explanation
on a single read, without stopping to work out what a sentence means.

Keep it short — but the single-read test above wins over brevity: if a step needs a
sentence to be followable, write that sentence. Cut what belongs to your work rather
than to my decision: no narration of how you investigated, no list of the files you
opened, no alternatives you considered and rejected, no restating the verdict at the
end. State the verdict, then why it holds, then what it breaks in practice.

<project-context>

This comment was saved as one of several findings in <review-comments-file-path>,
under slug `<slug>`. You do not need to open that file now — the comment above already
has everything relevant to this session. Cite the file path and slug later, if useful,
in the decision report.

Later in this session, you will be asked to write a decision report recording what was
ultimately decided about this comment and why. It belongs at <decision-file-path>. Do
not create or write that file now.

Do not modify any files yet.
