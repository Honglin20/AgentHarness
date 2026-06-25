# Big File — Token Audit Fixture

This file is deliberately large so the `read_text_file` tool produces a
measurable token cost in the audit. It is filler content repeated to reach
a few thousand tokens.

## Section 1

TODO: this is a marker line that Grep(content) should find. There are
several of these scattered through the file so the grep output is non-trivial.

Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod
tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim
veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea
commodo consequat. Duis aute irure dolor in reprehenderit in voluptate
velit esse cillum dolore eu fugiat nulla pariatur.

## Section 2

A sample function definition (for the `function` grep pattern):

    function add(a, b) {
        return a + b;
    }

TODO: second marker. The audit wants to see grep return multiple matches.

Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia
deserunt mollit anim id est laborum. Sed ut perspiciatis unde omnis iste
natus error sit voluptatem accusantium doloremque laudantium, totam rem
aperiam, eaque ipsa quae ab illo inventore veritatis et quasi architecto
beatae vitae dicta sunt explicabo.

## Section 3

Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit,
sed quia consequuntur magni dolores eos qui ratione voluptatem sequi
nesciunt. Neque porro quisquam est, qui dolorem ipsum quia dolor sit amet,
consectetur, adipisci velit, sed quia non numquam eius modi tempora
incidunt ut labore et dolore magnam aliquam quaerat voluptatem.

TODO: third marker. function helpers below.

    function multiply(x, y) {
        return x * y;
    }

Ut enim ad minima veniam, quis nostrum exercitationem ullam corporis
suscipit laboriosam, nisi ut aliquid ex ea commodi consequatur. Quis autem
vel eum iure reprehenderit qui in ea voluptate velit esse quam nihil
molestiae consequatur.

## Section 4

Vel illum qui dolorem eum fugiat quo voluptas nulla pariatur. At vero eos
et accusamus et iusto odio dignissimos ducimus qui blanditiis praesentium
voluptatum deleniti atque corrupti quos dolores.

function divide(numerator, denominator) {
    if (denominator === 0) throw new Error("divide by zero");
    return numerator / denominator;
}

TODO: fourth marker near the end.

## Section 5

Similique sunt in culpa qui officia deserunt mollitia animi, id est
laborum et dolorum fuga. Et harum quidem rerum facilis est et expedita
distinctio. Nam libero tempore, cum soluta nobis est eligendi optio
cumque nihil impedit quo minus id quod maxime placeat facere possimus.

function greet(name) {
    return "Hello, " + name;
}

Omnis voluptas assumenda est, omnis dolor repellendus. Temporibus autem
quibusdam et aut officiis debitis aut rerum necessitatibus saepe eveniet.

TODO: fifth and final marker. The grep for `function` should now return
roughly four match lines; the grep for `TODO` should return five.
