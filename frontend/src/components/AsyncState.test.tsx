import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AsyncState, Status } from "./AsyncState";

describe("AsyncState", () => {
  it("announces loading and errors", () => {
    const { rerender } = render(<AsyncState loading><span>内容</span></AsyncState>);
    expect(screen.getByRole("status")).toHaveTextContent("正在加载");
    rerender(<AsyncState error={new Error("网络失败")}><span>内容</span></AsyncState>);
    expect(screen.getByRole("alert")).toHaveTextContent("网络失败");
  });
  it("renders status text", () => {
    render(<Status value="healthy" />);
    expect(screen.getByText("正常")).toHaveClass("good");
  });
});
