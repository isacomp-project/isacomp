Hi there! Thanks for checking out isacomp.

isacomp is a research prototype intended to introduce a new way of doing processor design, different from HDLs or HLS.
It follows a flow from per-instruction ISA specifications, merges those to form single-cycle processors, and then through iterative microarchitectural refinement creates actually useful and performant implementations.
The framework includes a new language called .isa in which one writes their ISA specifications as short programs.
This is brought into a central intermediate representation (IR) called the resource graph, which can represent both architectural and microarchitectural details.
Because the implementation is extracted from the specification, one can traverse the resource graph to find useful information.
With this capability, isacomp transforms microarchitectural optimisation into an algorithmic process.
The creator of an optimisation writes an algorithm which takes input such as **where** to perform it, and then automatically analyses and transforms the resource graph accordingly.
The designer thus chooses **what** optimisation they want to perform from the available catalogue, and the **how** is handled automatically by the algorithm.

Essentially 100% of the code in this project was created in coordination with Claude.
That means there are plenty of rough edges throughout the repo.
The code is provided "as is" and no warranties are provided.
Note that I would provide a similar level of guarantee for any research code.
Just because you see a file in the repo doesn't mean you should expect it to do anything in particular.
If it is untested, it probably doesn't work, and even if it's tested, you should check carefully what the test actually checks.
If you report that something doesn't work, realise that I don't work for you and am just putting code on the internet for fun.
It is entirely my prerogative whether I will endeavour to fix the issue in question or not.
Having been an open source maintainer for over a decade, I am always happy to find time when I can to answer questions!

That said, you will see attempts at writing ISA-compatible specs for a variety of ISAs here (20+ as of initial release).
Some of those are quite functional, with their single-cycle implementations able to boot Linux inside Verilator simulation of extracted Verilog.
Others are quick hacky attempts that haven't been through even a single iteration of refinement.
It would be interesting if we could turn this into a broader library of specs covering a larger range of ISAs and ISA variants.

We also have a suite of optimisations, some of which help to produce quite interesting machines given the low effort they take.
One specific example is pipelining: You specify the edges you would like to cut in the single-cycle graph.
The optimisation can insert the pipeline registers, then analyse the new graph to identify potential hazards.
The user can then review the hazards and choose their preferred resolution strategy (stalling vs bypassing).
The hazard resolution optimisation can then automatically insert the corresponding logic.
This makes building differently pipelined machines just a matter of providing different arguments to the optimisations in question.

isacomp features a few language frontends (.isa, ILA, and SAIL for specs, annotated Verilog and VHDL for RTL) which are all broken to varying degrees.
It also features quite a number of language backends, though Verilog is really the only one that will work for anything particularly useful.
The most natural way to use isacomp is probably via its Python scripting interface, but there is also a tkinter GUI and a (very broken) wasm GUI which have some cool features.
There is also a prototype Rust implementation in the repo which has similar Python bindings to the original Python engine.
The Python engine may eventually be superseded, but we shall see.
Performance is generally not terrible but for the 1000+ instruction ISAs, runtime can get to be pretty bad.
Ideally the Rust engine should help resolve that.

If you'd like to read more about isacomp outside of the code, there's a short paper at LATTE 2026 which you can find [here](https://capra.cs.cornell.edu/latte26/paper/latte26-final25.pdf).
Acknowledgements and thanks go to my collaborators for their assistance in making the project possible as well as to Anthropic for providing a Max plan for several months.
